from __future__ import annotations

from types import SimpleNamespace
import pytest

from uniflora.discord_adapter import (
    _request_context,
    _message_request_context,
    _participant_identity,
    _privacy_metadata,
)

# Mock discord objects for testing
class MockRole:
    def __init__(self, id):
        self.id = id

class MockUser:
    def __init__(self, id, name="Test User", roles=None):
        self.id = id
        self.name = name
        self.display_name = name
        self.global_name = name
        self.roles = roles if roles is not None else []

class MockMessage:
    def __init__(self, author, channel, guild, id=1, content=""):
        self.author = author
        self.channel = channel
        self.guild = guild
        self.id = id
        self.content = content
        self.mentions = []
        self.reference = None

class MockInteraction:
    def __init__(self, user, channel_id, guild_id=None):
        self.user = user
        self.channel_id = channel_id
        self.guild_id = guild_id

def test_request_context_from_interaction_dm():
    user = MockUser(123)
    interaction = MockInteraction(user=user, channel_id=456)
    context = _request_context(interaction)
    assert context.guild_id is None
    assert context.channel_id == 456
    assert context.user_id == 123
    assert context.role_ids == frozenset()
    assert context.is_dm is True

def test_request_context_from_interaction_guild():
    user = MockUser(123, roles=[MockRole(789)])
    interaction = MockInteraction(user=user, channel_id=456, guild_id=789)
    context = _request_context(interaction)
    assert context.guild_id == 789
    assert context.channel_id == 456
    assert context.user_id == 123
    assert context.role_ids == frozenset([789])
    assert context.is_dm is False

def test_message_request_context_dm():
    user = MockUser(123)
    message = MockMessage(author=user, channel=SimpleNamespace(id=456), guild=None)
    context = _message_request_context(message)
    assert context.guild_id is None
    assert context.channel_id == 456
    assert context.user_id == 123
    assert context.role_ids == frozenset()
    assert context.is_dm is True

def test_message_request_context_guild():
    user = MockUser(123, roles=[MockRole(789)])
    message = MockMessage(
        author=user,
        channel=SimpleNamespace(id=456),
        guild=SimpleNamespace(id=789),
    )
    context = _message_request_context(message)
    assert context.guild_id == 789
    assert context.channel_id == 456
    assert context.user_id == 123
    assert context.role_ids == frozenset([789])
    assert context.is_dm is False

def test_participant_identity():
    user = MockUser(123, name="testuser")
    user.display_name = "Test User"
    user.global_name = "Global User"
    identity = _participant_identity(user)
    assert identity.discord_user_id == 123
    assert identity.names == ("testuser", "Test User", "Global User")

def test_privacy_metadata():
    author = MockUser(123, name="author")
    mentioned_user = MockUser(456, name="mentioned")
    
    message = MockMessage(
        id=789,
        author=author,
        channel=SimpleNamespace(id=101),
        guild=SimpleNamespace(id=112),
        content="Hello"
    )
    message.mentions = [mentioned_user]
    
    metadata = _privacy_metadata(message)
    
    assert metadata.current_participant.discord_user_id == 123
    assert len(metadata.referenced_participants) == 1
    assert metadata.referenced_participants[0].discord_user_id == 456
    
    assert "789" in metadata.sensitive_values
    assert "101" in metadata.sensitive_values
    assert "112" in metadata.sensitive_values

def test_privacy_metadata_with_reply():
    author = MockUser(123, name="author")
    replied_to_user = MockUser(789, name="replied_to")
    
    message = MockMessage(
        id=101112,
        author=author,
        channel=SimpleNamespace(id=101),
        guild=SimpleNamespace(id=112),
        content="Hello"
    )

    import discord
    reply_message = MockMessage(
        id=131415,
        author=replied_to_user,
        channel=SimpleNamespace(id=101),
        guild=SimpleNamespace(id=112),
        content="Original message"
    )
    # The `reference.resolved` is a `discord.Message` or `discord.DeletedReferencedMessage`.
    # `discord.DeletedReferencedMessage` doesn't have an `author`.
    # We will mock a `discord.Message`
    message.reference = SimpleNamespace(resolved=reply_message)
    
    metadata = _privacy_metadata(message)
    
    assert metadata.current_participant.discord_user_id == 123
    assert len(metadata.referenced_participants) == 1
    assert metadata.referenced_participants[0].discord_user_id == 789
