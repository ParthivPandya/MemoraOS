# Framework integrations

Two adapters exist. Neither has been benchmarked. Read what each was tested against before relying on it.

## LangChain retriever

```bash
pip install "memoraos[langchain]"
```

```python
from memoraos import MemoryOS
from memoraos.integrations.langchain import MemoraOSRetriever

mem = MemoryOS.local("./memory")
retriever = MemoraOSRetriever(memory=mem, user_id="me", top_k=5)
docs = retriever.invoke("What is the customer plan?")
```

`MemoraOSRetriever` is a `langchain_core` `BaseRetriever`. It returns **no documents** when MemoraOS has no supporting evidence (set `include_unsupported=True` to get the passages anyway), and each `Document` carries `memory_id`, `span_start`, `span_end`, `quote_sha256`, `verification`, and the recall's `answer` and `status` in its metadata, so the citation can be re-checked with `mem.verify_citations`. `as_of` answers as the memory stood at that time.

**Tested:** against `langchain-core` 1.8.4 on Python 3.14 (`tests/unit/test_langchain_retriever.py`, skipped when `langchain-core` is not installed; CI installs the `langchain` extra). **Not tested:** inside a LangChain chain or agent, with other `langchain-core` versions, or with LangGraph.

## Mem0-shaped `Memory`

```python
from memoraos.compat.mem0 import Memory

m = Memory(path="./memory")
m.add("My favorite color is blue.", user_id="alice")
m.search("What is my favorite color?", user_id="alice")["results"]
```

`memoraos.compat.mem0.Memory` has `add`, `search`, `get_all`, `get`, `update`, `delete`, `delete_all` and `history` with the argument names and return shapes of `mem0.Memory`, as read from the `mem0ai` 2.2.1 source. The tests (`tests/unit/test_mem0_compat.py`) check those shapes; **real Mem0 was never run against it**, so it is shape-compatible, not a verified drop-in.

Differences to expect:

- `infer` is ignored: text is stored as given and MemoraOS extracts facts with its own rules. Mem0 uses an LLM to decide what to store.
- `search` returns the evidence MemoraOS cites, and an empty list when it has no supporting evidence. A `memoraos` key with the answer, status and recall id is added to the response (not part of Mem0).
- `user_id`, `agent_id` and `run_id` collapse to one owner id (the first given); the others are kept as metadata.
- `get`, `update` and `delete` look the owner up from the memory id because Mem0's signatures carry none. Use it on a local, single-tenant store; it does no access control.
- `update` changes text only; `history` is built from MemoraOS memory versions (`ADD` and `UPDATE` events only).

## Not provided

- **CrewAI.** Current CrewAI memory expects a storage backend that takes precomputed embeddings and its own record types (`StorageBackend.save(records)`, `search(query_embedding, ...)`), which does not fit MemoraOS, and CrewAI could not be run here. No adapter was written rather than shipping one that is untested. Use the [MCP server](MCP.md) or the Python API directly.
- LlamaIndex, Haystack, AutoGen and other frameworks.
