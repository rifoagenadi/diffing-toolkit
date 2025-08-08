from typing import Any, Dict, List, Tuple
from html import escape
from tiny_dashboard.utils import apply_chat
from src.utils.model import has_thinking


class DualModelChatDashboard:
    """
    Minimal, reusable dual-model chat component.

    Assumptions (fail-fast):
    - method.generate_text(prompt, model_type, max_length, temperature, do_sample) exists
    - method.tokenizer exists and is compatible with tiny_dashboard.utils.apply_chat
    - method has 'cfg' for has_thinking checks
    - two model types are available: "base" and "finetuned"
    """

    def __init__(self, method_instance, title: str = "Dual-Model Chat") -> None:
        self.method = method_instance
        self.title = title

    def _session_keys(self) -> Dict[str, str]:
        method_key = f"dual_chat_{self.method.__class__.__name__.lower()}"
        return {
            "history": f"{method_key}_history",  # legacy aggregated
            "history_base": f"{method_key}_history_base",
            "history_ft": f"{method_key}_history_ft",
            "input": f"{method_key}_input",
            "reset_input": f"{method_key}_reset_input",
            "send_target": f"{method_key}_send_target",
            "use_chat": f"{method_key}_use_chat",
            "temperature": f"{method_key}_temperature",
            "max_length": f"{method_key}_max_length",
            "do_sample": f"{method_key}_do_sample",
            "thinking": f"{method_key}_enable_thinking",
        }

    def _build_prompt_for_model(
        self,
        history: List[Dict[str, str]],
        next_user_message: str,
        use_chat_formatting: bool,
        enable_thinking: bool,
        model_key: str,
    ) -> str:
        # model_key kept for validation only
        assert model_key in ("base", "finetuned"), f"Unexpected model_key: {model_key}"
        pieces: List[str] = []
        for turn in history:
            assert "user" in turn, "Each turn must contain 'user'"
            pieces.append(turn["user"])
            if use_chat_formatting:
                pieces.append("<eot>")
            # Per-model history stores assistant under a common key
            if "assistant" in turn:
                pieces.append(turn["assistant"])
                if use_chat_formatting:
                    pieces.append("<eot>")
        pieces.append(next_user_message)
        if use_chat_formatting:
            pieces.append("<eot>")
        prompt = "".join(pieces)
        if use_chat_formatting:
            prompt = apply_chat(prompt, self.method.tokenizer, add_bos=False, enable_thinking=enable_thinking)
        return prompt

    def _build_formatted_prompt_and_user_segment(
        self,
        history: List[Dict[str, str]],
        next_user_message: str,
        use_chat_formatting: bool,
        enable_thinking: bool,
        model_key: str,
    ) -> Tuple[str, str]:
        """Return full formatted prompt and the formatted segment for the new user turn.

        The user segment includes the formatted user block and any assistant-start tokens,
        e.g. "<|im_start|>user ... <|im_end|> <|im_start|>assistant".
        """
        assert model_key in ("base", "finetuned")

        # Previous formatted (history is already stored as formatted 'user' + assistant-only)
        prev_formatted_parts: List[str] = []
        for turn in history:
            assert "user" in turn
            prev_formatted_parts.append(turn["user"])  # already formatted segment up to assistant-start
            if "assistant" in turn:
                prev_formatted_parts.append(turn["assistant"])  # assistant-only tokens
        prev_formatted = "".join(prev_formatted_parts)

        # Formatted user segment for the next message
        if use_chat_formatting:
            # Passing a single-turn text with an <eot> produces "<|im_start|>user ... <|im_end|><|im_start|>assistant"
            single_turn_text = f"{next_user_message}<eot>"
            user_segment = apply_chat(
                single_turn_text,
                self.method.tokenizer,
                add_bos=False,
                enable_thinking=enable_thinking,
            )
        else:
            user_segment = next_user_message

        full_formatted = prev_formatted + user_segment
        return full_formatted, user_segment

    def _strip_prompt_from_output(self, generated_text: str, prompt_formatted: str) -> str:
        """Cut the prompt tokens from model output using tokenizer lengths, not string prefix.

        Ensures that the assistant message begins right after the prompt, preserving special tokens
        like <think>. Fail fast if the output is shorter than the prompt in token space.
        """
        tokenizer = self.method.tokenizer
        prompt_ids = tokenizer.encode(prompt_formatted, add_special_tokens=False)
        output_ids = tokenizer.encode(generated_text, add_special_tokens=False)

        assert isinstance(prompt_ids, list) and isinstance(output_ids, list)
        assert len(output_ids) >= len(prompt_ids), (
            f"Output shorter than prompt: output={len(output_ids)} prompt={len(prompt_ids)}"
        )

        assistant_ids = output_ids[len(prompt_ids):]
        assistant_text = tokenizer.decode(assistant_ids, skip_special_tokens=False)
        return assistant_text

    def _render_chat_column(self, title: str, history: List[Dict[str, str]]) -> None:
        """Render a single model's chat history as chat bubbles."""
        import streamlit as st

        css = """<style>
.chat-thread { padding: 4px 0; }
.chat-title { font-weight: 600; margin-bottom: 6px; }
.msg { margin: 6px 0; display: flex; }
.msg.user { justify-content: flex-start; }
.msg.assistant { justify-content: flex-end; }
.bubble { max-width: 92%; padding: 10px 12px; border-radius: 14px; line-height: 1.35; white-space: pre-wrap; word-break: break-word; }
.user .bubble { background: #f3f4f6; border: 1px solid #e5e7eb; color: #111827; }
.assistant .bubble { background: #e8f5ff; border: 1px solid #cfe8ff; color: #0f172a; }
.role { font-size: 12px; opacity: 0.7; margin-bottom: 2px; }
</style>"""

        parts: List[str] = [css, f'<div class="chat-thread"><div class="chat-title">{escape(title)}</div>']
        for turn in history:
            # user
            user_text = escape(turn["user"]) if "user" in turn else ""
            if user_text:
                parts.append('<div class="msg user"><div><div class="role">User</div><div class="bubble">' + user_text + '</div></div></div>')
            # assistant
            asst_text = escape(turn.get("assistant", ""))
            if asst_text:
                parts.append('<div class="msg assistant"><div><div class="role">Assistant</div><div class="bubble">' + asst_text + '</div></div></div>')
        parts.append('</div>')
        st.markdown("".join(parts), unsafe_allow_html=True)

    def display(self) -> None:
        import streamlit as st

        st.markdown(f"### {self.title}")
        st.caption("Chat side-by-side with the base and finetuned models. The first message is sent to both; subsequent messages continue the multi-turn dialogue with both models.")

        keys = self._session_keys()
        if keys["history_base"] not in st.session_state:
            st.session_state[keys["history_base"]] = []  # List[{ 'user': str, 'assistant': str }]
        if keys["history_ft"] not in st.session_state:
            st.session_state[keys["history_ft"]] = []
        # Migrate legacy aggregated history once (if present)
        if keys["history"] in st.session_state and not st.session_state[keys["history_base"]] and not st.session_state[keys["history_ft"]]:
            legacy = st.session_state[keys["history"]]
            assert isinstance(legacy, list), "Legacy history must be a list"
            for turn in legacy:
                assert "user" in turn, "Legacy turn missing 'user'"
                if "base" in turn:
                    st.session_state[keys["history_base"]].append({"user": turn["user"], "assistant": turn["base"]})
                if "finetuned" in turn:
                    st.session_state[keys["history_ft"]].append({"user": turn["user"], "assistant": turn["finetuned"]})
        if keys["input"] not in st.session_state:
            st.session_state[keys["input"]] = ""
        if keys["use_chat"] not in st.session_state:
            st.session_state[keys["use_chat"]] = True
        if keys["temperature"] not in st.session_state:
            st.session_state[keys["temperature"]] = 1.0
        if keys["max_length"] not in st.session_state:
            st.session_state[keys["max_length"]] = 200
        if keys["do_sample"] not in st.session_state:
            st.session_state[keys["do_sample"]] = True
        if keys["thinking"] not in st.session_state:
            st.session_state[keys["thinking"]] = False
        if keys["reset_input"] not in st.session_state:
            st.session_state[keys["reset_input"]] = False
        if keys["send_target"] not in st.session_state:
            st.session_state[keys["send_target"]] = "both"

        # Handle input reset BEFORE instantiating the text_area widget
        if st.session_state[keys["reset_input"]]:
            st.session_state[keys["input"]] = ""
            st.session_state[keys["reset_input"]] = False

        with st.expander("Settings", expanded=False):
            cols = st.columns(4)
            with cols[0]:
                st.checkbox(
                    "Use Chat Formatting",
                    key=keys["use_chat"],
                    help="Format prompts via chat template. Uses <eot> turn separators."
                )
            with cols[1]:
                temperature = st.slider(
                    "Temperature",
                    min_value=0.1,
                    max_value=2.0,
                    value=st.session_state[keys["temperature"]],
                    step=0.1,
                    key=keys["temperature"],
                )
            with cols[2]:
                max_length = st.slider(
                    "Max Length",
                    min_value=10,
                    max_value=500,
                    value=st.session_state[keys["max_length"]],
                    key=keys["max_length"],
                )
            with cols[3]:
                do_sample = st.checkbox(
                    "Do Sample",
                    key=keys["do_sample"],
                    value=st.session_state[keys["do_sample"]],
                )
            if has_thinking(self.method.cfg):
                st.session_state[keys["thinking"]] = st.checkbox(
                    "Enable Thinking",
                    value=st.session_state[keys["thinking"]],
                    help="Include thinking tokens when formatting chat",
                )

        # Conversation display (chat bubbles)
        col_base, col_ft = st.columns(2)
        with col_base:
            self._render_chat_column("Base model", st.session_state[keys["history_base"]])
        with col_ft:
            self._render_chat_column("Finetuned model", st.session_state[keys["history_ft"]])

        # Input + actions
        st.text_area(
            "Your message",
            key=keys["input"],
            height=100,
            placeholder="Type your message...",
        )

        # Target selection and actions
        target_col, clear_col, send_col = st.columns([1.4, 1, 1.2])
        with target_col:
            st.radio(
                "Send to",
                options=["both", "base", "finetuned"],
                index=["both", "base", "finetuned"].index(st.session_state[keys["send_target"]]),
                key=keys["send_target"],
                horizontal=True,
            )
        with clear_col:
            clear_clicked = st.button("Clear", use_container_width=True)
        with send_col:
            send_clicked = st.button("Send", type="primary", use_container_width=True)

        if clear_clicked:
            st.session_state[keys["history_base"]] = []
            st.session_state[keys["history_ft"]] = []
            st.session_state[keys["reset_input"]] = True
            st.rerun()

        if send_clicked:
            msg = (st.session_state[keys["input"]] or "").strip()
            assert len(msg) > 0, "Message cannot be empty"

            enable_thinking = bool(st.session_state[keys["thinking"]])
            use_chat_formatting = bool(st.session_state[keys["use_chat"]])
            temperature = float(st.session_state[keys["temperature"]])
            max_length = int(st.session_state[keys["max_length"]])
            do_sample = bool(st.session_state[keys["do_sample"]])

            send_target = st.session_state[keys["send_target"]]
            assert send_target in ("both", "base", "finetuned"), "Invalid send_target"

            if send_target in ("both", "base"):
                prompt_base, user_segment_base = self._build_formatted_prompt_and_user_segment(
                    st.session_state[keys["history_base"]], msg, use_chat_formatting, enable_thinking, model_key="base"
                )
                with st.spinner("Generating (base) ..."):
                    reply_base = self.method.generate_text(
                        prompt=prompt_base,
                        model_type="base",
                        max_length=max_length,
                        temperature=temperature,
                        do_sample=do_sample,
                    )
                assistant_only_base = self._strip_prompt_from_output(reply_base, prompt_base)
                st.session_state[keys["history_base"]].append({"user": user_segment_base, "assistant": assistant_only_base})

            if send_target in ("both", "finetuned"):
                prompt_ft, user_segment_ft = self._build_formatted_prompt_and_user_segment(
                    st.session_state[keys["history_ft"]], msg, use_chat_formatting, enable_thinking, model_key="finetuned"
                )
                with st.spinner("Generating (finetuned) ..."):
                    reply_ft = self.method.generate_text(
                        prompt=prompt_ft,
                        model_type="finetuned",
                        max_length=max_length,
                        temperature=temperature,
                        do_sample=do_sample,
                    )
                assistant_only_ft = self._strip_prompt_from_output(reply_ft, prompt_ft)
                st.session_state[keys["history_ft"]].append({"user": user_segment_ft, "assistant": assistant_only_ft})
            st.session_state[keys["reset_input"]] = True
            st.rerun()