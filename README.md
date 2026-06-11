# AICL

### Adaptive Inter-Module Communication Language

A lightweight, extensible communication and orchestration framework for modular AI systems.

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MPL--2.0-green)
![Status](https://img.shields.io/badge/status-active-brightgreen)

---

## Overview

AICL (Adaptive Inter-Module Communication Language) is an open-source framework designed to simplify communication between AI modules, agents, reasoning systems, memory systems, and orchestration components.

Instead of tightly coupling every component together, AICL provides a standardized packet-based communication layer, intelligent routing, service discovery, health monitoring, and safety middleware.

Think of AICL as the communication backbone of a modular AI architecture.

---

## Why AICL?

As AI systems become more complex, they are increasingly built from multiple specialized components:

* Reasoning engines
* Memory systems
* Planning agents
* Safety layers
* Tool integrations
* Knowledge retrieval modules
* Local and cloud models

Managing communication between these components quickly becomes difficult.

AICL provides:

* Structured packet communication
* Dynamic module discovery
* Concurrent routing
* Safety enforcement
* Health monitoring
* Extensible architecture

---

## Core Architecture

```text
                    ┌──────────────┐
                    │ Application  │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Safety Layer │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │    Router    │
                    └──────┬───────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
  ┌──────────┐      ┌──────────┐      ┌──────────┐
  │ Memory   │      │ Reasoner │      │ Planner  │
  └──────────┘      └──────────┘      └──────────┘

          Registry + Health Monitoring
```

---

# Features

## AICL Packet System

The packet system provides a structured communication format between modules.

Features:

* Packet validation
* Metadata support
* Trace tracking
* Intent tagging
* Confidence tracking
* Packet merging
* Immutable-safe operations

---

## Router

Concurrent packet routing engine.

Features:

* ThreadPool-based execution
* Directed routing
* Broadcast messaging
* Multicast messaging
* Timeout handling
* Retry logic
* Exponential backoff
* Health-aware routing
* Middleware hooks

---

## Registry

Thread-safe module registry with persistence.

Features:

* Module registration
* Capability discovery
* Priority-based selection
* Tags and metadata
* Heartbeat monitoring
* Health tracking
* Event subscriptions
* Persistent storage

---

## Safety Layer

Two-tier safety architecture.

### Tier 1 — Safety Rules

Simple rule engine for lightweight validation.

```python
from aicl import SafetyRules

rules = SafetyRules()

rules.add_rule(
    lambda p: "forbidden" not in p.symbols
)

rules.enforce(packet)
```

### Tier 2 — Safety Layer

Production-grade middleware.

Features:

* Rate limiting
* Replay detection
* Duplicate suppression
* Sensitive pattern scanning
* Blacklist filtering
* Loop detection
* Audit logging
* Kill switch support
* Optional ML safety hooks

---

# Installation

Clone the repository:

```bash
git clone https://github.com/LocalHouseLLM/AICL.git
cd AICL
```

Install locally:

```bash
pip install -e .
```

Future PyPI release:

```bash
pip install aicl
```

---

# Quick Start

## Creating a Packet

```python
from aicl import AICLPacket

packet = AICLPacket(
    origin="user",
    symbols=["hello", "world"]
)
```

---

## Registering a Module

```python
from aicl import Router

router = Router()

def echo(packet):
    return packet

router.register_module(
    "echo",
    echo,
    capabilities=["chat"]
)
```

---

## Sending a Packet

```python
packet = AICLPacket(
    origin="user",
    symbols=["hello"]
)

response = router.request_response(
    packet,
    target="echo"
)

print(response.pretty())
```

---

## Using Capability Routing

```python
router.register_module(
    "reasoner",
    reason,
    capabilities=["reason"]
)

packet.intent = "reason"

responses = router.send(packet)
```

The router automatically discovers compatible modules.

---

## Safety Middleware

```python
from aicl import Router
from aicl import SafetyLayer

safety = SafetyLayer()

router = Router(
    pre_route_hook=safety.pre_route,
    post_route_hook=safety.post_route
)
```

---

# Example Use Cases

AICL can be used for:

* Multi-agent systems
* Modular AI architectures
* Local AI orchestration
* Research platforms
* Autonomous workflows
* Tool-calling systems
* Distributed reasoning experiments
* AI safety experimentation

---

# Roadmap

## Current

* Packet communication
* Concurrent routing
* Persistent registry
* Health monitoring
* Safety middleware

## Planned

* AICL Symbol Language (AICL-SL)
* Binary packet encoding
* Distributed transports
* Scheduler subsystem
* Observability dashboard
* Advanced orchestration primitives

---

# Performance Philosophy

AICL focuses on:

* Simplicity
* Low overhead
* Debuggability
* Safety
* Extensibility

The goal is not to replace existing AI frameworks, but to provide a clean communication layer that can connect them together.

---

# Contributing

Contributions are welcome.

Areas of interest:

* Routing strategies
* Safety mechanisms
* Distributed transports
* Documentation
* Benchmarks
* Integrations
* Testing

Pull requests and discussions are encouraged.

---

# License

This project is licensed under the Mozilla Public License 2.0 (MPL-2.0).

You may build proprietary systems on top of AICL while improvements to AICL itself remain open and shareable.

---

# Author

**Vansh Bukkarwal**

Creator of AICL and the LocalHouseLLM ecosystem.

---

## Vision

AICL is being developed as a foundational communication layer for future modular AI systems, enabling independent components to collaborate through a unified protocol while remaining flexible, transparent, and extensible.

If you're interested in modular AI, agent architectures, orchestration systems, or open AI infrastructure, you're in the right place.
