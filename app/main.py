import asyncio, json, os, re, shlex, shutil, subprocess, sys
from asyncio.subprocess import PIPE, STDOUT
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel

CFG = Path(os.getenv("CONFIG_DIR", "/config"))
DATA = Path(os.getenv("DATA_DIR", "/data"))
MAX_STEPS, MAX_OUT = 20, 20000  # tool-loop turns, chars returned per ssh call
HISTORY = int(os.getenv("HISTORY_MESSAGES", "20"))  # past messages resent to the brain per request (keep even)


def seed():
    CFG.mkdir(parents=True, exist_ok=True)
    for f in (Path(__file__).parent / "defaults").iterdir():
        if not (CFG / f.name).exists():
            shutil.copy(f, CFG / f.name)
    key = CFG / "ssh" / "id_ed25519"
    key.parent.mkdir(exist_ok=True)
    if not key.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key), "-C", "swarm"], check=True)
    print("Add this public key to authorized_keys on your machines:\n" + key.with_suffix(".pub").read_text())


if sys.argv[1:] == ["seed"]:
    seed()
    sys.exit()

TOKEN = os.environ["SWARM_TOKEN"]  # ponytail: static bearer token, put behind tailscale only
llm = AsyncOpenAI(base_url=os.environ["LITELLM_URL"], api_key=os.environ["LITELLM_MASTER_KEY"])
app = FastAPI(title="Swarm")

# re-read on every request so editing the yaml needs no restart
models = lambda: yaml.safe_load((CFG / "models.yaml").read_text())
hosts = lambda: yaml.safe_load((CFG / "hosts.yaml").read_text())


async def ssh(host, cmd, timeout=60):
    h = hosts().get(host)
    if not h:
        return f"unknown host {host!r}; known: {list(hosts())}"
    p = await asyncio.create_subprocess_exec(
        "ssh", "-i", str(CFG / "ssh/id_ed25519"), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={CFG}/ssh/known_hosts",
        f"{h['user']}@{h['address']}", cmd, stdout=PIPE, stderr=STDOUT)
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        return "timeout"
    return out.decode(errors="replace")[:MAX_OUT]


async def read(host, path):
    q = shlex.quote(path)
    return await ssh(host, f"if [ -d {q} ]; then ls -la {q}; else head -c {MAX_OUT} {q}; fi")


async def run(host, command):
    if not hosts().get(host, {}).get("exec"):
        return f"exec not allowed on {host!r}"
    return await ssh(host, command, timeout=300)


async def delegate(model, task, files=()):
    m = models()[model]
    budget = int(m["context"] * 3 * 0.6)  # chars; leave room for the answer
    body = ""
    for f in files:  # files go straight to the worker, never through the brain's context
        body += f"\n\n### {f['host']}:{f['path']}\n{await read(f['host'], f['path'])}"
    prompt = task + body[: max(0, budget - len(task))]
    try:
        r = await llm.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}], max_tokens=m.get("max_output", 4096))
        return r.choices[0].message.content
    except Exception as e:  # let the brain retry with another model
        return f"worker {model} failed: {e}"


def tools():
    host_prop = {"type": "string", "enum": list(hosts())}
    fn = lambda name, desc, props: {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": list(props) if name != "delegate" else ["model", "task"]}}}
    return [
        fn("delegate", "Run a task on a cheaper worker model. Call several in one turn to run them in parallel. "
           "Attach files so the worker reads them directly.",
           {"model": {"type": "string", "enum": list(models())}, "task": {"type": "string"},
            "files": {"type": "array", "items": {"type": "object", "required": ["host", "path"],
                      "properties": {"host": host_prop, "path": {"type": "string"}}}}}),
        fn("read", "Read a file (or list a directory) on a remote machine.",
           {"host": host_prop, "path": {"type": "string"}}),
        fn("run", "Run a shell command on a remote machine (only hosts with exec: true).",
           {"host": host_prop, "command": {"type": "string"}}),
    ]


async def run_tool(tc):
    try:
        return await {"delegate": delegate, "read": read, "run": run}[tc.function.name](**json.loads(tc.function.arguments))
    except Exception as e:
        return f"tool error: {e}"


SYSTEM = """You are the orchestrator. Do trivial or judgment-heavy work yourself. Delegate bulk, mechanical or \
well-scoped work to workers, in parallel when independent, choosing the model whose strengths fit and whose \
context fits the input. Review and merge worker output; retry or switch model if it is poor.

Worker catalog:
{models}
Machines (SSH): {hosts}"""


def cache_tail(msgs):
    # one Anthropic cache breakpoint on the newest message: each loop step re-reads the prefix at ~10% price
    *head, last = msgs
    return [*head, {**last, "content": [{"type": "text", "text": last["content"], "cache_control": {"type": "ephemeral"}}]}]


class Ask(BaseModel):
    prompt: str
    session: str | None = None  # no session = stateless, nothing stored or resent


def auth(authorization: str = Header("")):
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(401)


@app.post("/ask", dependencies=[Depends(auth)])
async def ask(req: Ask):
    f = None
    history = []
    if req.session:
        if not re.fullmatch(r"[\w-]+", req.session):
            raise HTTPException(400, "bad session id")
        f = DATA / "sessions" / f"{req.session}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():  # ponytail: sliding window, summarize old turns with a worker if you need long memory
            saved = json.loads(f.read_text())
            history = saved[max(0, len(saved) - HISTORY):] if HISTORY else []
    turn = {"role": "user", "content": req.prompt}
    msgs = [{"role": "system", "content": SYSTEM.format(
        models=yaml.safe_dump(models()), hosts={k: "exec" if v.get("exec") else "read-only" for k, v in hosts().items()})},
        *history, turn]
    usage = {"in": 0, "cached": 0, "out": 0}  # brain tokens only; workers are tracked by LiteLLM
    for _ in range(MAX_STEPS):
        r = await llm.chat.completions.create(model="brain", messages=cache_tail(msgs), tools=tools(), max_tokens=8192)
        usage["in"] += r.usage.prompt_tokens
        usage["out"] += r.usage.completion_tokens
        usage["cached"] += getattr(r.usage.prompt_tokens_details, "cached_tokens", 0) or 0
        m = r.choices[0].message
        msgs.append(m.model_dump(exclude_none=True))
        if not m.tool_calls:
            if f:
                f.write_text(json.dumps([*history, turn, {"role": "assistant", "content": m.content}]))
            return {"answer": m.content, "usage": usage}
        results = await asyncio.gather(*map(run_tool, m.tool_calls))
        msgs += [{"role": "tool", "tool_call_id": tc.id, "content": out} for tc, out in zip(m.tool_calls, results)]
    return {"answer": f"stopped after {MAX_STEPS} steps without finishing", "usage": usage}
