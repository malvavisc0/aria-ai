"""Tests for SQLAlchemy models."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aria.db.models import Element, Feedback, Step, Thread, User


class TestUserModel:
    """Test suite for User model."""

    @pytest.mark.asyncio
    async def test_user_creation(self, db_session: AsyncSession):
        """Test creating a user record."""
        user = User(
            id=str(uuid.uuid4()),
            identifier="test@example.com",
            display_name="Test User",
            metadata_='{"key": "value"}',
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add(user)
        await db_session.commit()

        # Verify user exists
        result = await db_session.execute(select(User).where(User.id == user.id))
        retrieved_user = result.scalar_one()
        assert retrieved_user is not None
        assert retrieved_user.identifier == "test@example.com"

    @pytest.mark.asyncio
    async def test_user_metadata_column_mapping(self, db_session: AsyncSession):
        """Test metadata_ attribute maps to metadata column."""
        user = User(
            id=str(uuid.uuid4()),
            identifier="test@example.com",
            display_name="Test User",
            metadata_='{"test": true}',
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add(user)
        await db_session.commit()

        # Query using raw SQL to verify column name
        from sqlalchemy import text

        result = await db_session.execute(
            text("SELECT metadata FROM users WHERE id = :id"), {"id": user.id}
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == '{"test": true}'

    @pytest.mark.asyncio
    async def test_user_unique_identifier(self, db_session: AsyncSession):
        """Test user identifier uniqueness constraint."""
        user1 = User(
            id=str(uuid.uuid4()),
            identifier="duplicate@example.com",
            display_name="Duplicate User",
            metadata_="{}",
            createdAt="2024-01-01T00:00:00Z",
        )
        user2 = User(
            id=str(uuid.uuid4()),
            identifier="duplicate@example.com",
            display_name="Duplicate User 2",
            metadata_="{}",
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add(user1)
        await db_session.commit()

        db_session.add(user2)
        with pytest.raises(IntegrityError):
            await db_session.commit()


class TestThreadModel:
    """Test suite for Thread model."""

    @pytest.mark.asyncio
    async def test_thread_creation(self, db_session: AsyncSession):
        """Test creating a thread record."""
        thread = Thread(
            id=str(uuid.uuid4()),
            name="Test Thread",
            tags='["tag1", "tag2"]',
            metadata_='{"key": "value"}',
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add(thread)
        await db_session.commit()

        result = await db_session.execute(select(Thread).where(Thread.id == thread.id))
        retrieved_thread = result.scalar_one()
        assert retrieved_thread.name == "Test Thread"

    @pytest.mark.asyncio
    async def test_thread_user_relationship(self, db_session: AsyncSession):
        """Test thread-user relationship."""
        user = User(
            id=str(uuid.uuid4()),
            identifier="test@example.com",
            display_name="Test User",
            metadata_="{}",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(user)
        await db_session.flush()

        thread = Thread(
            id=str(uuid.uuid4()),
            userId=user.id,
            name="Test Thread",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(thread)
        await db_session.commit()

        # Test relationship from thread to user
        result = await db_session.execute(select(Thread).where(Thread.id == thread.id))
        retrieved_thread = result.scalar_one()
        # Note: Relationship loading may require explicit loading in async context
        assert retrieved_thread.userId == user.id


class TestCascadeDeletes:
    """Test suite for cascade delete behavior."""

    @pytest.mark.asyncio
    async def test_delete_user_cascades_to_threads(self, db_session: AsyncSession):
        """Test deleting user cascades to threads."""
        user = User(
            id=str(uuid.uuid4()),
            identifier="test@example.com",
            display_name="Test User",
            metadata_="{}",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(user)
        await db_session.flush()

        thread = Thread(
            id=str(uuid.uuid4()),
            userId=user.id,
            name="Test Thread",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(thread)
        await db_session.commit()

        thread_id = thread.id

        # Delete user
        await db_session.delete(user)
        await db_session.commit()

        # Verify thread is also deleted
        result = await db_session.execute(select(Thread).where(Thread.id == thread_id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_thread_cascades_to_steps(self, db_session: AsyncSession):
        """Test deleting thread cascades to steps."""
        thread = Thread(
            id=str(uuid.uuid4()),
            name="Test Thread",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(thread)
        await db_session.flush()

        step = Step(
            id=str(uuid.uuid4()),
            threadId=thread.id,
            name="Test Step",
            type="tool",
            streaming=False,
        )
        db_session.add(step)
        await db_session.commit()

        step_id = step.id

        # Delete thread
        await db_session.delete(thread)
        await db_session.commit()

        # Verify step is also deleted
        result = await db_session.execute(select(Step).where(Step.id == step_id))
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_thread_cascades_to_elements(self, db_session: AsyncSession):
        """Test deleting thread cascades to elements."""
        thread = Thread(
            id=str(uuid.uuid4()),
            name="Test Thread",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(thread)
        await db_session.flush()

        element = Element(
            id=str(uuid.uuid4()),
            threadId=thread.id,
            name="Test Element",
        )
        db_session.add(element)
        await db_session.commit()

        element_id = element.id

        # Delete thread
        await db_session.delete(thread)
        await db_session.commit()

        # Verify element is also deleted
        result = await db_session.execute(
            select(Element).where(Element.id == element_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_delete_thread_cascades_to_feedbacks(self, db_session: AsyncSession):
        """Test deleting thread cascades to feedbacks."""
        thread = Thread(
            id=str(uuid.uuid4()),
            name="Test Thread",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(thread)
        await db_session.flush()

        feedback = Feedback(
            id=str(uuid.uuid4()),
            threadId=thread.id,
            forId=str(uuid.uuid4()),
            value=1,
        )
        db_session.add(feedback)
        await db_session.commit()

        feedback_id = feedback.id

        # Delete thread
        await db_session.delete(thread)
        await db_session.commit()

        # Verify feedback is also deleted
        result = await db_session.execute(
            select(Feedback).where(Feedback.id == feedback_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_full_cascade_delete(self, db_session: AsyncSession):
        """Test full cascade: user -> thread -> steps/elements/feedbacks."""
        user = User(
            id=str(uuid.uuid4()),
            identifier="test@example.com",
            display_name="Test User",
            metadata_="{}",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(user)
        await db_session.flush()

        thread = Thread(
            id=str(uuid.uuid4()),
            userId=user.id,
            name="Test Thread",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(thread)
        await db_session.flush()

        step = Step(
            id=str(uuid.uuid4()),
            threadId=thread.id,
            name="Test Step",
            type="tool",
            streaming=False,
        )
        element = Element(id=str(uuid.uuid4()), threadId=thread.id, name="Test Element")
        feedback = Feedback(
            id=str(uuid.uuid4()),
            threadId=thread.id,
            forId=step.id,
            value=1,
        )

        db_session.add_all([step, element, feedback])
        await db_session.commit()

        step_id, element_id, feedback_id = step.id, element.id, feedback.id

        # Delete user
        await db_session.delete(user)
        await db_session.commit()

        # Verify all related records are deleted
        assert (
            await db_session.execute(select(Step).where(Step.id == step_id))
        ).scalar_one_or_none() is None
        assert (
            await db_session.execute(select(Element).where(Element.id == element_id))
        ).scalar_one_or_none() is None
        assert (
            await db_session.execute(select(Feedback).where(Feedback.id == feedback_id))
        ).scalar_one_or_none() is None


class TestModelRelationships:
    """Test suite for model relationships."""

    @pytest.mark.asyncio
    async def test_user_threads_relationship(self, db_session: AsyncSession):
        """Test accessing threads through user relationship."""
        user = User(
            id=str(uuid.uuid4()),
            identifier="test@example.com",
            display_name="Test User",
            metadata_="{}",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(user)
        await db_session.flush()

        thread1 = Thread(
            id=str(uuid.uuid4()),
            userId=user.id,
            name="Thread 1",
            createdAt="2024-01-01T00:00:00Z",
        )
        thread2 = Thread(
            id=str(uuid.uuid4()),
            userId=user.id,
            name="Thread 2",
            createdAt="2024-01-01T00:00:00Z",
        )

        db_session.add_all([thread1, thread2])
        await db_session.commit()

        # Query threads for user
        result = await db_session.execute(
            select(Thread).where(Thread.userId == user.id)
        )
        threads = result.scalars().all()
        assert len(threads) == 2

    @pytest.mark.asyncio
    async def test_thread_steps_relationship(self, db_session: AsyncSession):
        """Test accessing steps through thread relationship."""
        thread = Thread(
            id=str(uuid.uuid4()),
            name="Test Thread",
            createdAt="2024-01-01T00:00:00Z",
        )
        db_session.add(thread)
        await db_session.flush()

        step1 = Step(
            id=str(uuid.uuid4()),
            threadId=thread.id,
            name="Step 1",
            type="tool",
            streaming=False,
        )
        step2 = Step(
            id=str(uuid.uuid4()),
            threadId=thread.id,
            name="Step 2",
            type="llm",
            streaming=False,
        )

        db_session.add_all([step1, step2])
        await db_session.commit()

        # Query steps for thread
        result = await db_session.execute(
            select(Step).where(Step.threadId == thread.id)
        )
        steps = result.scalars().all()
        assert len(steps) == 2
