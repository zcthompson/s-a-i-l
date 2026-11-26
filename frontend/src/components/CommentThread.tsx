import { useState, useEffect } from 'react';
import { api, getAuthUsername, getAuthIsAdmin } from '../lib/api';
import { Comment } from '../types/use_case';

interface CommentThreadProps {
  useCaseId: number;
  useCaseTitle?: string;
  onBack?: () => void;
}

const editBtnStyle = {
  padding: '4px 10px',
  background: 'var(--brand-50)',
  color: 'var(--brand-700)',
  border: '1px solid var(--brand-500)',
  borderRadius: 'var(--radius-sm)',
  cursor: 'pointer',
  fontSize: '0.75rem',
};

const deleteBtnStyle = {
  padding: '4px 10px',
  background: 'var(--status-negative-soft)',
  color: 'var(--status-negative)',
  border: '1px solid var(--status-negative)',
  borderRadius: 'var(--radius-sm)',
  cursor: 'pointer',
  fontSize: '0.75rem',
};

export function CommentThread({ useCaseId, useCaseTitle, onBack }: CommentThreadProps) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [newComment, setNewComment] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editContent, setEditContent] = useState('');
  const [busy, setBusy] = useState(false);
  const username = getAuthUsername();
  const isAdmin = getAuthIsAdmin();

  // Author or admin may edit/delete (backend enforces the same rule; this
  // only controls the UI affordances).
  const canModify = (comment: Comment) =>
    isAdmin || (username !== '' && comment.user_name === username);

  const fetchComments = async () => {
    try {
      setLoading(true);
      const data = await api.getComments(useCaseId);
      setComments(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load comments');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchComments();
  // eslint-disable-next-line react-hooks/exhaustive-deps -- pre-existing dependency list; change only with UI verification
  }, [useCaseId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newComment.trim()) return;

    try {
      await api.createComment(useCaseId, newComment);
      setNewComment('');
      await fetchComments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to post comment');
    }
  };

  const startEdit = (comment: Comment) => {
    setEditingId(comment.id);
    setEditContent(comment.content);
    setError(null);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditContent('');
  };

  const handleSaveEdit = async (commentId: number) => {
    if (!editContent.trim() || busy) return;
    setBusy(true);
    try {
      await api.updateComment(commentId, editContent);
      cancelEdit();
      await fetchComments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save comment');
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (comment: Comment) => {
    if (!window.confirm('Delete this comment? This cannot be undone.')) return;
    setBusy(true);
    try {
      await api.deleteComment(comment.id);
      if (editingId === comment.id) cancelEdit();
      await fetchComments();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete comment');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ marginTop: '2rem', padding: '1.5rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow-sm)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <h3 style={{ margin: 0, color: 'var(--neutral-700)' }}>
          💬 Comments &amp; Collaboration{useCaseTitle ? <> — {useCaseTitle}</> : null}
        </h3>
        {onBack && (
          <button role="button" aria-label="Back to use case detail"
            onClick={onBack}
            style={{
              padding: '8px 16px',
              background: 'var(--neutral-500)',
              color: 'var(--neutral-0)',
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
          >
            ← Back to Detail
          </button>
        )}
      </div>
      <div style={{ marginBottom: '1rem', fontSize: '0.8rem', color: 'var(--neutral-500)' }}>
        {username
          ? <>Posting as <strong style={{ color: 'var(--brand-700)' }}>{username}</strong> — use @username to mention a teammate</>
          : 'Not signed in'}
      </div>
      <form onSubmit={handleSubmit} style={{ marginBottom: '1.5rem' }}>
        <textarea aria-label="Type a comment... Use @username for mentions"
          placeholder="Type a comment... Use @username for mentions"
          value={newComment}
          onChange={e => setNewComment(e.target.value)}
          rows={3}
          style={{ width: '100%', padding: '12px', border: '1px solid var(--divider)', borderRadius: 'var(--radius)', resize: 'vertical', fontFamily: 'inherit', background: 'var(--neutral-0)', color: 'var(--ink)' }}
        />
        <button role="button" aria-label="Post comment"
          type="submit"
          disabled={!newComment.trim()}
          style={{ marginTop: '0.5rem', padding: '8px 16px', background: (!newComment.trim()) ? 'var(--neutral-400)' : 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: (!newComment.trim()) ? 'not-allowed' : 'pointer', fontWeight: 'bold' }}
        >
          Post Comment
        </button>
      </form>
      {error && (
        <div role="alert" aria-live="assertive" style={{ padding: '0.75rem', background: 'var(--status-negative-soft)', borderLeft: '4px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', color: 'var(--status-negative)', marginBottom: '1rem' }}>
          <span aria-hidden="true">⚠️ </span>{error}
          <button role="button" aria-label="Retry loading comments" onClick={fetchComments} style={{ marginLeft: '12px', border: '1px solid var(--status-negative)', borderRadius: 'var(--radius-sm)', background: 'var(--neutral-0)', color: 'var(--status-negative)', cursor: 'pointer' }}>Retry</button>
        </div>
      )}
      {loading ? (
        <div role="status" aria-live="polite" style={{ textAlign: 'center', padding: '2rem', color: 'var(--neutral-500)' }}>Loading comments…</div>
      ) : comments.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--neutral-500)', fontStyle: 'italic' }}>No comments yet. Start the conversation!</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {comments.map((comment) => (
            <div key={comment.id} style={{ padding: '1rem', background: 'var(--neutral-0)', borderRadius: 'var(--radius)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
                <strong style={{ color: 'var(--brand-700)' }}>{comment.user_name}</strong>
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {canModify(comment) && (
                    <>
                      <button role="button" aria-label={`Edit comment by ${comment.user_name}`}
                        onClick={() => startEdit(comment)}
                        style={editBtnStyle}
                      >
                        ✏️ Edit
                      </button>
                      <button role="button" aria-label={`Delete comment by ${comment.user_name}`}
                        onClick={() => handleDelete(comment)}
                        style={deleteBtnStyle}
                      >
                        🗑 Delete
                      </button>
                    </>
                  )}
                  <span style={{ fontSize: '0.8rem', color: 'var(--neutral-500)' }}>{new Date(comment.created_at).toLocaleString()}</span>
                </span>
              </div>
              {editingId === comment.id ? (
                <div>
                  <textarea
                    aria-label="Edit comment"
                    value={editContent}
                    onChange={e => setEditContent(e.target.value)}
                    rows={3}
                    style={{ width: '100%', padding: '12px', border: '1px solid var(--neutral-400)', borderRadius: 'var(--radius)', resize: 'vertical', fontFamily: 'inherit', background: 'var(--neutral-0)', color: 'var(--ink)', marginBottom: '0.5rem' }}
                  />
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button role="button" aria-label="Save comment edit"
                      onClick={() => handleSaveEdit(comment.id)}
                      disabled={busy || !editContent.trim()}
                      style={{ padding: '6px 14px', background: (busy || !editContent.trim()) ? 'var(--neutral-400)' : 'var(--brand-500)', color: 'var(--neutral-0)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: (busy || !editContent.trim()) ? 'not-allowed' : 'pointer', fontWeight: 'bold' }}
                    >
                      Save
                    </button>
                    <button role="button" aria-label="Cancel comment edit"
                      onClick={cancelEdit}
                      style={{ padding: '6px 14px', background: 'var(--divider)', color: 'var(--neutral-700)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div style={{ lineHeight: '1.5' }}>
                  {comment.content.split(/(@\w+)/).map((part: string, i: number) =>
                    part.startsWith('@') ? (
                      <span key={i} style={{ background: 'var(--brand-50)', padding: '2px 4px', borderRadius: 'var(--radius-sm)', fontWeight: 'bold' }}>{part}</span>
                    ) : (
                      part
                    )
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
export default CommentThread;
