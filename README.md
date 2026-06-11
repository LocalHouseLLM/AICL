# AICL — Adaptive Inter-Module Communication Language
### High-Performance Communication Protocol for Modular AI Systems  
**Author:** Vansh Bukkarwal — LocalHouseLLM Project  
**License:** Mozilla Public License 2.0 (MPL-2.0)

---

## 🚀 Overview

AICL (Adaptive Inter-Module Communication Language) is a **high-performance symbolic communication protocol** designed for modular AI architectures — including ANVIRA, AMA-MRL, hierarchical agent systems, distributed reasoning engines, and model-agnostic AI pipelines.

AICL enables AI modules to:

- Communicate using a **compact symbolic language**  
- Exchange structured messages with **zero ambiguity**  
- Route tasks dynamically with **high concurrency**  
- Enforce safety rules and policies  
- Register, orchestrate, and monitor modules cleanly  

AICL functions as the **nervous system** of an AI, connecting reasoning units, safety layers, translators, memory systems, and self-learning modules.

---

## 📦 Features

### 📨 AICL Packet System
- Efficient symbolic message format  
- Intent, confidence, metadata, and tracing baked in  
- Self-validating packets with error reporting  
- Merge & transform operations  
- AI-friendly minimal overhead design  

### 🔀 Router
- Concurrent dispatch (sync + async modules)  
- Directed routing / broadcast / multicast  
- Timeout, retry, and backoff support  
- Pre-route and post-route safety hooks  
- Async inbox system for worker modules  

### 📚 Registry
- Persistent module registry  
- Metadata, capabilities, and health status  
- Automatic integrity checks  
- JSON or DB storage adapters  

### 🛡 Safety System
- Rule-based packet validation  
- Blocking, mutation, or passthrough modes  
- System-wide safety enforcement  
- Rogue module protection  

### 🧰 Utility Helpers
- High-precision timestamps  
- UUID-based packet IDs  
- Freeze / unfreeze utilities  
- Zero extra dependencies  

---

## 🗂 Directory Structure

AICL/
│
├── init.py
├── packet.py
├── router.py
├── registry.py
├── safety.py
└── utils/
├── init.py
└── helpers.py
LICENSE
README.md


---

## 🔧 Installation

### From source:

```bash
git clone https://github.com/localhousellm/AICL.git
cd AICL

(Future) PyPI:
pip install aicl


🧪 Minimal Example
Creating and sending a packet
from AICL import AICLPacket, Router

router = Router()

def echo(pkt):
    return AICLPacket(
        origin="echo",
        symbols=[f"Echo: {pkt.symbols}"]
    )

router.register_module("echo_module", echo)

p = AICLPacket(origin="user", symbols=["hello", "world"])
resp = router.request_response(p, target="echo_module")

print(resp.pretty())


🛡 Safety Example
from AICL import SafetyRules, SafetyViolation

rules = SafetyRules()

# Block packets containing a forbidden keyword
rules.add_rule(
    lambda p: "forbidden" not in p.symbols
    or SafetyViolation("Forbidden term detected")
)

packet = AICLPacket(origin="test", symbols=["this", "is", "forbidden"])

try:
    rules.enforce(packet)
except SafetyViolation as v:
    print("Blocked:", v)

🔌 Example Module Adapter
handler = Router.make_module_adapter_from_callable(
    lambda text: text.upper(),
    name="upper_module"
)

router.register_module("upper", handler)


📈 Vision

AICL is designed to act as the communication backbone for:
Adaptive Modular AI (AMA)
ANVIRA Cognitive Architecture
LocalHouseLLM multi-agent systems
Distributed reasoning clusters
Edge-device AI orchestration

AICL is built for:

Speed
Clarity
Debuggability
Safety
Extensibility

This is the 1.0.0 foundational release, prepared for public open-source use.


🤝 Contributing

Contributions are welcome!

You can submit PRs for:
New routing strategies
Additional safety rules

Packet extensions
Async optimizations
Documentation and examples
Tooling & integrations
MPL-2.0 ensures contributors keep credit while allowing open evolution.


📜 License

This project is licensed under the Mozilla Public License 2.0 (MPL-2.0).
Modifications to AICL source files must be shared, but your project built on top of AICL can be proprietary.


⭐ Support the Project

If you find AICL useful:

Star ⭐ the repository
Share with researchers and engineers
Contribute modules or improvements
Integrate AICL into your AI architecture

Let’s build open, modular, adaptive AI together.