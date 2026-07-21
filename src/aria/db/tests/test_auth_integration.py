"""Integration tests for authentication with password field."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aria.db.auth import hash_password, verify_password
from aria.db.models import User


class TestPasswordAuthentication:
    """Test suite for password authentication flow."""

    @pytest.mark.asyncio
    async def test_password_authentication_flow(self, db_session: AsyncSession):
        """Test complete password authentication flow."""
        # Create user with password
        password = "secure_password_123"
        password_hash = hash_password(password)

        user = User(
            id=str(uuid.uuid4()),
            identifier="user@example.com",
            display_name="Test User",
            metadata_='{"role": "user"}',
            password=password_hash,
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add(user)
        await db_session.commit()

        # Retrieve user and verify password
        result = await db_session.execute(
            select(User).where(User.identifier == "user@example.com")
        )
        retrieved_user = result.scalar_one()

        # Correct password should verify
        assert retrieved_user.password is not None
        assert verify_password(password, retrieved_user.password)

        # Wrong password should not verify
        assert retrieved_user.password is not None
        assert not verify_password("wrong_password", retrieved_user.password)

    @pytest.mark.asyncio
    async def test_password_hash_uniqueness(self, db_session: AsyncSession):
        """Test that same password produces different hashes (due to salt)."""
        password = "same_password"

        # Create two users with same password
        user1 = User(
            id=str(uuid.uuid4()),
            identifier="user1@example.com",
            display_name="User One",
            metadata_='{"role": "user"}',
            password=hash_password(password),
            createdAt="2024-01-01T00:00:00Z",
        )

        user2 = User(
            id=str(uuid.uuid4()),
            identifier="user2@example.com",
            display_name="User Two",
            metadata_='{"role": "user"}',
            password=hash_password(password),
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add_all([user1, user2])
        await db_session.commit()

        # Hashes should be different (different salts)
        assert str(user1.password) != str(user2.password)

        # But both should verify with the same password
        assert user1.password is not None
        assert user2.password is not None
        assert verify_password(password, user1.password)
        assert verify_password(password, user2.password)

    @pytest.mark.asyncio
    async def test_user_without_password_authentication(self, db_session: AsyncSession):
        """Test that users without passwords cannot authenticate."""
        user = User(
            id=str(uuid.uuid4()),
            identifier="oauth@example.com",
            display_name="OAuth User",
            metadata_='{"role": "user", "provider": "google"}',
            password=None,
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add(user)
        await db_session.commit()

        # Retrieve user
        result = await db_session.execute(
            select(User).where(User.identifier == "oauth@example.com")
        )
        retrieved_user = result.scalar_one()

        # User has no password
        assert retrieved_user.password is None

    @pytest.mark.asyncio
    async def test_password_update(self, db_session: AsyncSession):
        """Test updating user password."""
        # Create user with initial password
        old_password = "old_password"
        user = User(
            id=str(uuid.uuid4()),
            identifier="user@example.com",
            display_name="Test User",
            metadata_='{"role": "user"}',
            password=hash_password(old_password),
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add(user)
        await db_session.commit()

        # Update password
        new_password = "new_password"
        user.password = hash_password(new_password)
        await db_session.commit()

        # Retrieve user
        result = await db_session.execute(
            select(User).where(User.identifier == "user@example.com")
        )
        retrieved_user = result.scalar_one()

        # Old password should not work
        assert retrieved_user.password is not None
        assert not verify_password(old_password, retrieved_user.password)

        # New password should work
        assert verify_password(new_password, retrieved_user.password)
