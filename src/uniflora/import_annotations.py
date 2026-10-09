from __future__ import annotations

from pathlib import Path
import py_compile
import shutil
import sys


ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "src" / "uniflora" / "discord_adapter.py"
INTERPRETATION = ROOT / "src" / "uniflora" / "interpretation.py"


def replace_once(text: str, old: str, new: str, label: str) -> tuple[str, bool]:
    if new in text:
        print(f"[already applied] {label}")
        return text, False
    if old not in text:
        raise RuntimeError(
            f"Could not find the expected block for: {label}\n"
            "No files were overwritten after this failure."
        )
    return text.replace(old, new, 1), True


def main() -> int:
    if not ADAPTER.exists():
        raise FileNotFoundError(ADAPTER)
    if not INTERPRETATION.exists():
        raise FileNotFoundError(INTERPRETATION)

    adapter_original = ADAPTER.read_text(encoding="utf-8")
    interpretation_original = INTERPRETATION.read_text(encoding="utf-8")

    adapter = adapter_original
    interpretation = interpretation_original
    changed_adapter = False
    changed_interpretation = False

    adapter, changed = replace_once(
        adapter,
        '''            rendered = await self._with_phase_footer(result.text, decision.environment)
            await message.channel.send(f"{marker}{rendered}")
            await self._announce_current_position(decision.environment, message.channel)
''',
        '''            rendered = await self._with_phase_footer(result.text, decision.environment)
            for chunk in self._discord_chunks(rendered, marker):
                await message.channel.send(
                    chunk,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            await self._announce_current_position(decision.environment, message.channel)
''',
        "chunk natural-language channel replies",
    )
    changed_adapter |= changed

    adapter, changed = replace_once(
        adapter,
        '''        chunks = self._discord_chunks(rendered, marker)
        if view is None:
            await interaction.response.send_message(chunks[0])
        else:
            await interaction.response.send_message(
                chunks[0],
                view=view,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk)
''',
        '''        chunks = self._discord_chunks(rendered, marker)
        send_options: dict[str, Any] = {
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if view is not None:
            send_options["view"] = view

        if interaction.response.is_done():
            await interaction.followup.send(chunks[0], **send_options)
        else:
            await interaction.response.send_message(chunks[0], **send_options)

        for chunk in chunks[1:]:
            await interaction.followup.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
            )
''',
        "allow _send to work after an interaction is deferred",
    )
    changed_adapter |= changed

    adapter, changed = replace_once(
        adapter,
        '''        async def recall(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            if self.game is None:
''',
        '''        async def recall(interaction: discord.Interaction) -> None:
            environment = await self._authorize_player(interaction)
            if environment is None:
                return
            await interaction.response.defer()
            if self.game is None:
''',
        "defer /interior recall before slower work",
    )
    changed_adapter |= changed

    adapter, changed = replace_once(
        adapter,
        '''        async def test_export(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            if self.operations is None:
''',
        '''        async def test_export(interaction: discord.Interaction) -> None:
            environment = await self._authorize_admin(interaction, Environment.TEST)
            if environment is None:
                return
            await interaction.response.defer()
            if self.operations is None:
''',
        "defer /interior test export before generating the export",
    )
    changed_adapter |= changed

    adapter, changed = replace_once(
        adapter,
        '''            await interaction.response.send_message(
                f"{marker}Test export; the environment label is embedded.", file=attachment
            )
''',
        '''            await interaction.followup.send(
                f"{marker}Test export; the environment label is embedded.",
                file=attachment,
                allowed_mentions=discord.AllowedMentions.none(),
            )
''',
        "send the deferred test export through followup",
    )
    changed_adapter |= changed

    interpretation, changed = replace_once(
        interpretation,
        '''        except Exception:
            await self._record_provider_failure(ref)
            logger.warning(
                "OpenAI interpretation failed",
                extra={"environment": environment.value, "purpose": "interpretation"},
            )
            return NaturalLanguageResult(True, self._fallback("interpretation failed"), True)
''',
        '''        except Exception:
            await self._record_provider_failure(ref)
            logger.exception(
                "OpenAI interpretation failed",
                extra={"environment": environment.value, "purpose": "interpretation"},
            )
            return NaturalLanguageResult(True, self._fallback("interpretation failed"), True)
''',
        "log the complete OpenAI interpretation traceback",
    )
    changed_interpretation |= changed

    # Compile temporary files before touching the project.
    adapter_temp = ADAPTER.with_suffix(".transport-fix.tmp.py")
    interpretation_temp = INTERPRETATION.with_suffix(".logging-fix.tmp.py")
    adapter_temp.write_text(adapter, encoding="utf-8")
    interpretation_temp.write_text(interpretation, encoding="utf-8")

    try:
        py_compile.compile(str(adapter_temp), doraise=True)
        py_compile.compile(str(interpretation_temp), doraise=True)
    except Exception:
        adapter_temp.unlink(missing_ok=True)
        interpretation_temp.unlink(missing_ok=True)
        raise

    if changed_adapter:
        shutil.copy2(ADAPTER, ADAPTER.with_name("discord_adapter.before-transport-fix.py"))
        ADAPTER.write_text(adapter, encoding="utf-8")
    if changed_interpretation:
        shutil.copy2(
            INTERPRETATION,
            INTERPRETATION.with_name("interpretation.before-error-logging.py"),
        )
        INTERPRETATION.write_text(interpretation, encoding="utf-8")

    adapter_temp.unlink(missing_ok=True)
    interpretation_temp.unlink(missing_ok=True)

    py_compile.compile(str(ADAPTER), doraise=True)
    py_compile.compile(str(INTERPRETATION), doraise=True)

    print("Patch complete.")
    print(f"Adapter changed: {changed_adapter}")
    print(f"Interpreter changed: {changed_interpretation}")
    print("Both active files compile successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
