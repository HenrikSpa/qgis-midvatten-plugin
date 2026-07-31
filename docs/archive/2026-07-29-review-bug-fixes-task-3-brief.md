> **ARCHIVED** — point-in-time document; does not reflect current code.
> created: 2026-07-29 · modified: 2026-07-29 · archived: 2026-07-31

### Task 3: Guard `_log_on_main_thread` against None `bar_msg`

`_log_on_main_thread` unconditionally calls `QgsApplication.messageLog().logMessage(returnunicode(bar_msg), ...)` at line 133 even when `bar_msg is None`. Since `returnunicode(None)` returns `""`, every `log_msg`-only call (40 call sites) produces a spurious empty entry in the QGIS message log panel.

**Files:**
- Modify: `tools/utils/message_utils.py:133-135`
- Test: `test/test_midvatten_utils.py`

**Interfaces:**
- Consumes: `QgsApplication.messageLog().logMessage` (QGIS API)
- Produces: No new interfaces — conditional guard on existing call

- [ ] **Step 1: Write the failing test**

Add to the `TestMessageDispatcher` class in `test/test_midvatten_utils.py`:

```python
    def test_log_msg_only_does_not_produce_empty_bar_entry(self):
        """When only log_msg is supplied, the bar_msg log entry must be skipped."""
        with mock.patch("qgis.utils.iface") as mock_iface:
            mock_log = mock.MagicMock()
            with mock.patch(
                "midvatten.tools.utils.message_utils.QgsApplication"
            ) as mock_app:
                mock_app.messageLog.return_value = mock_log
                message_utils.MessagebarAndLog._log_on_main_thread(
                    log_msg="detail only"
                )

        logged_messages = [
            call.args[0] for call in mock_log.logMessage.call_args_list
        ]
        assert "" not in logged_messages
        assert "detail only" in logged_messages
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest test/test_midvatten_utils.py::TestMessageDispatcher::test_log_msg_only_does_not_produce_empty_bar_entry -xvs`
Expected: FAIL — `""` appears in `logged_messages` because line 133 logs `returnunicode(None)`.

- [ ] **Step 3: Fix the guard in `_log_on_main_thread`**

In `tools/utils/message_utils.py`, replace lines 133–135:

```python
        QgsApplication.messageLog().logMessage(
            returnunicode(bar_msg), "Midvatten", level=log_level
        )
```

with:

```python
        if bar_msg is not None:
            QgsApplication.messageLog().logMessage(
                returnunicode(bar_msg), "Midvatten", level=log_level
            )
```

This moves the `bar_msg` log entry inside a guard, matching the bar_msg
widget guard already present at line 112. When only `log_msg` is supplied,
only the `log_msg` entry (lines 136–139) is written.

- [ ] **Step 4: Run the test and full utils suite**

Run: `python3 -m pytest test/test_midvatten_utils.py -x`
Expected: All tests pass.

- [ ] **Step 5: Lint and commit**

```bash
ruff check --fix tools/utils/message_utils.py test/test_midvatten_utils.py
ruff format tools/utils/message_utils.py test/test_midvatten_utils.py
git add tools/utils/message_utils.py test/test_midvatten_utils.py
git commit -m "fix(message_utils): skip empty bar_msg log entry when only log_msg is set

_log_on_main_thread unconditionally logged returnunicode(bar_msg) even
when bar_msg was None, producing a spurious empty string in the QGIS
message log panel for every log_msg-only call (40 call sites). Guard it
the same way the messagebar widget creation is already guarded.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Final verification

After all three tasks:

```bash
python3 -m pytest test/test_wlevels_calc_calibr.py test/test_midvatten_utils.py -x
```

Expected: All tests pass. No regressions.
