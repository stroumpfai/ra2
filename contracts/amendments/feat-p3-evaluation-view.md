# Amendment: `tests/e2e/test_j6_egress.py`

## Which file

`tests/e2e/test_j6_egress.py` — A5's, owner of the layer-4 gates
(`plan-m0-m5.md` §4). Not listed in `CONTRACTS.md`, but outside this branch's
owned paths, so it is proposed here rather than edited.

Specifically `test_the_served_html_names_no_other_host`'s allow-set:

```python
if _host(url) not in {_host(server_url), "127.0.0.1", "localhost", *XML_NAMESPACES}
```

## Why

`_host()` is `urlsplit(url).netloc`, which **includes the port**. The
Evaluation view renders the configured LLM endpoint as a label — the design
draws it twice, "endpoint http://127.0.0.1:11434/v1 · reachable" under the
Models card (`design/prompt-evaluation/README.md` §2 step 4) and
"endpoint 127.0.0.1:11434" on the reproducibility card. The first spelling
makes `_host()` return `127.0.0.1:11434`, which is not `127.0.0.1`, so the
gate reads a loopback address as a foreign host and fails `/evaluation`.

Nothing about that is egress. The URL is a **label**: it is never fetched by
the browser, and `test_no_page_load_reaches_any_other_host` — the half of J6
that actually watches the wire — passes unchanged. The gate's own intent is
CLAUDE.md's "Loopback only" rule, and this endpoint is loopback by
construction (`OllamaLLMClient` refuses anything else at construction, with no
opt-out).

The case simply could not arise in phase 1: there was no endpoint to name, and
the bare `127.0.0.1` / `localhost` entries in the allow-set suggest the author
anticipated a loopback literal without anticipating a port on it.

## The diff

Compare loopback on **hostname**, not on netloc:

```diff
 def _host(url: str) -> str:
     return urlsplit(url).netloc


+#: Loopback names a page may *name* (never fetch), port and all. N1 became
+#: "loopback only" at phase 3 (CLAUDE.md, "Loopback only"), and the
+#: Evaluation view renders the configured endpoint as a label.
+LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
+
+
 @pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda i: i.key)
 def test_the_served_html_names_no_other_host(page, server_url, item):
     response = page.request.get(f"{server_url}{item.path}")
     assert response.ok
     offenders = [
         url
         for url in ABSOLUTE_URL.findall(response.text())
-        if _host(url) not in {_host(server_url), "127.0.0.1", "localhost", *XML_NAMESPACES}
+        if _host(url) != _host(server_url)
+        and urlsplit(url).hostname not in LOOPBACK
+        and _host(url) not in XML_NAMESPACES
     ]
     assert offenders == [], f"{item.path} names external URLs: {offenders}"
```

`test_no_page_load_reaches_any_other_host` and
`test_navigating_the_whole_nav_reaches_no_other_host` are **unchanged**: they
watch what the browser actually requests, and nothing should relax there.

## What this branch did instead

Shimmed inside its own path, as CLAUDE.md's ownership rule asks. The view
renders the endpoint through `evaluation_view._endpoint_text()`, which strips
the scheme — so both places read `127.0.0.1:11434/v1`, which is the design's
own reproducibility-card spelling and matches no `//`-anchored URL. No test is
`xfail`ed and `just e2e` is green.

If this amendment is accepted, `_endpoint_text` can be deleted and step 4 can
render `connection.endpoint` verbatim, which is one word closer to the drawn
board. If it is rejected, the shim is the permanent answer and the design
README should record that the endpoint is rendered without its scheme.
