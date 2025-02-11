import asyncio
import json
from typing import AsyncIterable, Awaitable, List, Optional
from uuid import UUID
from repository.brain import get_brain_by_id

from langchain.callbacks.streaming_aiter import AsyncIteratorCallbackHandler
from langchain.chains import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain.llms.base import BaseLLM
from langchain.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
)
from logger import get_logger
from models.chats import ChatQuestion
from models.databases.supabase.chats import CreateChatHistory
from models.prompt import Prompt
from pydantic import BaseModel
from repository.chat import (
    GetChatHistoryOutput,
    format_chat_history,
    format_history_to_openai_mesages,
    get_chat_history,
    update_chat_history,
    update_message_by_id,
)

from llm.utils.get_prompt_to_use import get_prompt_to_use
from llm.utils.get_prompt_to_use_id import get_prompt_to_use_id

logger = get_logger(__name__)
SYSTEM_MESSAGE = "Your name is a Digital Twin - . You're a helpful assistant. If you don't know the answer, just say that you don't know, don't try to make up an answer."

class StringModifier:
    def __init__(self, default_prompt):
        self.default_prompt = default_prompt

    def add_string_at_index(self, additional_string, index):
        first_part = self.default_prompt[:index]
        second_part = self.default_prompt[index:]
        prompt_content = first_part + additional_string + second_part
        return prompt_content

    def modify_default_prompt(self, new_prompt):
        self.default_prompt = new_prompt

class HeadlessQA(BaseModel):
    model: str = None  # type: ignore
    temperature: float = 0.0
    max_tokens: int = 256
    user_openai_api_key: str = None  # type: ignore
    openai_api_key: str = None  # type: ignore
    streaming: bool = False
    chat_id: str = None  # type: ignore
    callbacks: List[AsyncIteratorCallbackHandler] = None  # type: ignore
    prompt_id: Optional[UUID]

    def _determine_api_key(self, openai_api_key, user_openai_api_key):
        """If user provided an API key, use it."""
        if user_openai_api_key is not None:
            return user_openai_api_key
        else:
            return openai_api_key

    def _determine_streaming(self, model: str, streaming: bool) -> bool:
        """If the model name allows for streaming and streaming is declared, set streaming to True."""
        return streaming

    def _determine_callback_array(
        self, streaming
    ) -> List[AsyncIteratorCallbackHandler]:  # pyright: ignore reportPrivateUsage=none
        """If streaming is set, set the AsyncIteratorCallbackHandler as the only callback."""
        if streaming:
            return [
                AsyncIteratorCallbackHandler()  # pyright: ignore reportPrivateUsage=none
            ]

    def __init__(self, **data):
        super().__init__(**data)

        self.openai_api_key = self._determine_api_key(
            self.openai_api_key, self.user_openai_api_key
        )
        self.streaming = self._determine_streaming(
            self.model, self.streaming
        )  # pyright: ignore reportPrivateUsage=none
        self.callbacks = self._determine_callback_array(
            self.streaming
        )  # pyright: ignore reportPrivateUsage=none

    @property
    def prompt_to_use(self) -> Optional[Prompt]:
        return get_prompt_to_use(None, self.prompt_id)

    @property
    def prompt_to_use_id(self) -> Optional[UUID]:
        return get_prompt_to_use_id(None, self.prompt_id)

    def _create_llm(
        self, model, temperature=0, streaming=False, callbacks=None
    ) -> BaseLLM:
        """
        Determine the language model to be used.
        :param model: Language model name to be used.
        :param streaming: Whether to enable streaming of the model
        :param callbacks: Callbacks to be used for streaming
        :return: Language model instance
        """
        return ChatOpenAI(
            temperature=temperature,
            model=model,
            streaming=streaming,
            verbose=True,
            callbacks=callbacks,
            openai_api_key=self.openai_api_key,
        )  # pyright: ignore reportPrivateUsage=none

    def _create_prompt_template(self):
        messages = [
            HumanMessagePromptTemplate.from_template("{question}"),
        ]
        CHAT_PROMPT = ChatPromptTemplate.from_messages(messages)
        return CHAT_PROMPT

    def generate_answer(
        self, chat_id: UUID, question: ChatQuestion
    ) -> GetChatHistoryOutput:
        transformed_history = format_chat_history(get_chat_history(self.chat_id))

        modifier = StringModifier(SYSTEM_MESSAGE)
        brain = get_brain_by_id(self.brain_id)

        prompt_content = (
            self.prompt_to_use.content if self.prompt_to_use else modifier.add_string_at_index(brain.name, 29)
        )

        messages = format_history_to_openai_mesages(
            transformed_history, prompt_content, question.question
        )
        answering_llm = self._create_llm(
            model=self.model, streaming=False, callbacks=self.callbacks
        )
        model_prediction = answering_llm.predict_messages(
            messages  # pyright: ignore reportPrivateUsage=none
        )
        answer = model_prediction.content

        new_chat = update_chat_history(
            CreateChatHistory(
                **{
                    "chat_id": chat_id,
                    "user_message": question.question,
                    "assistant": answer,
                    "brain_id": None,
                    "prompt_id": self.prompt_to_use_id,
                }
            )
        )

        return GetChatHistoryOutput(
            **{
                "chat_id": chat_id,
                "user_message": question.question,
                "assistant": answer,
                "message_time": new_chat.message_time,
                "prompt_title": self.prompt_to_use.title
                if self.prompt_to_use
                else None,
                "brain_name": None,
                "message_id": new_chat.message_id,
            }
        )

    async def generate_stream(
        self, chat_id: UUID, question: ChatQuestion
    ) -> AsyncIterable:
        callback = AsyncIteratorCallbackHandler()
        self.callbacks = [callback]

        transformed_history = format_chat_history(get_chat_history(self.chat_id))

        modifier = StringModifier(SYSTEM_MESSAGE)
        brain = get_brain_by_id(self.brain_id)

        prompt_content = (
            self.prompt_to_use.content if self.prompt_to_use else modifier.add_string_at_index(brain.name, 29)
        )

        messages = format_history_to_openai_mesages(
            transformed_history, prompt_content, question.question
        )
        answering_llm = self._create_llm(
            model=self.model, streaming=True, callbacks=self.callbacks
        )

        CHAT_PROMPT = ChatPromptTemplate.from_messages(messages)
        headlessChain = LLMChain(llm=answering_llm, prompt=CHAT_PROMPT)

        response_tokens = []

        async def wrap_done(fn: Awaitable, event: asyncio.Event):
            try:
                await fn
            except Exception as e:
                logger.error(f"Caught exception: {e}")
            finally:
                event.set()

        run = asyncio.create_task(
            wrap_done(
                headlessChain.acall({}),
                callback.done,
            ),
        )

        streamed_chat_history = update_chat_history(
            CreateChatHistory(
                **{
                    "chat_id": chat_id,
                    "user_message": question.question,
                    "assistant": "",
                    "brain_id": None,
                    "prompt_id": self.prompt_to_use_id,
                }
            )
        )

        streamed_chat_history = GetChatHistoryOutput(
            **{
                "chat_id": str(chat_id),
                "message_id": streamed_chat_history.message_id,
                "message_time": streamed_chat_history.message_time,
                "user_message": question.question,
                "assistant": "",
                "prompt_title": self.prompt_to_use.title
                if self.prompt_to_use
                else None,
                "brain_name": None,
            }
        )

        async for token in callback.aiter():
            logger.info("Token: %s", token)
            response_tokens.append(token)
            streamed_chat_history.assistant = token
            yield f"data: {json.dumps(streamed_chat_history.dict())}"

        await run
        assistant = "".join(response_tokens)

        update_message_by_id(
            message_id=str(streamed_chat_history.message_id),
            user_message=question.question,
            assistant=assistant,
        )

    class Config:
        arbitrary_types_allowed = True
