"""
Performance Optimization Migration

Adds database indexes for frequently queried columns.
Run this after deployment to optimize query performance.
"""
from alembic import op
import sqlalchemy as sa

# Revision identifiers
revision = 'perf_001_add_indexes'
down_revision = None  # Set to your last migration
branch_labels = None
depends_on = None


def upgrade():
    """Add performance indexes."""
    
    # Task table indexes - most frequently queried
    op.create_index('idx_task_user_id', 'tasks', ['user_id'])
    op.create_index('idx_task_status', 'tasks', ['status'])
    op.create_index('idx_task_user_status', 'tasks', ['user_id', 'status'])
    op.create_index('idx_task_created_at', 'tasks', ['created_at'])
    op.create_index('idx_task_user_created', 'tasks', ['user_id', 'created_at'])
    op.create_index('idx_task_status_created', 'tasks', ['status', 'created_at'])
    
    # GeneratedClip table indexes
    op.create_index('idx_clip_task_id', 'generated_clips', ['task_id'])
    op.create_index('idx_clip_virality_score', 'generated_clips', ['virality_score'])
    op.create_index('idx_clip_created_at', 'generated_clips', ['created_at'])
    op.create_index('idx_clip_task_virality', 'generated_clips', ['task_id', 'virality_score'])
    
    # Source table indexes
    op.create_index('idx_source_url', 'sources', ['url'])
    op.create_index('idx_source_type', 'sources', ['type'])
    
    # User table indexes
    op.create_index('idx_user_email', 'users', ['email'])
    op.create_index('idx_user_created', 'users', ['createdAt'])
    
    print("✅ Performance indexes created successfully")


def downgrade():
    """Remove performance indexes."""
    
    # Task table
    op.drop_index('idx_task_user_id', table_name='tasks')
    op.drop_index('idx_task_status', table_name='tasks')
    op.drop_index('idx_task_user_status', table_name='tasks')
    op.drop_index('idx_task_created_at', table_name='tasks')
    op.drop_index('idx_task_user_created', table_name='tasks')
    op.drop_index('idx_task_status_created', table_name='tasks')
    
    # GeneratedClip table
    op.drop_index('idx_clip_task_id', table_name='generated_clips')
    op.drop_index('idx_clip_virality_score', table_name='generated_clips')
    op.drop_index('idx_clip_created_at', table_name='generated_clips')
    op.drop_index('idx_clip_task_virality', table_name='generated_clips')
    
    # Source table
    op.drop_index('idx_source_url', table_name='sources')
    op.drop_index('idx_source_type', table_name='sources')
    
    # User table
    op.drop_index('idx_user_email', table_name='users')
    op.drop_index('idx_user_created', table_name='users')
    
    print("✅ Performance indexes removed")
