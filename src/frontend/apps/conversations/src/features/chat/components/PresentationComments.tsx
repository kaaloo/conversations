import { Button } from '@gouvfr-lasuite/cunningham-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Box, Icon, Text } from '@/components';
import {
  type PresentationComment,
  createPresentationComment,
  listPresentationComments,
  resolvePresentationComment,
} from '@/features/chat/api/presentationComments';

/**
 * Slide-anchored comments on a sidecar deck (slides-loop POC, P4).
 *
 * Comments are the rework bridge: the user pins feedback to a slide, then
 * asks the assistant to revise. The assistant's revise tool reads the
 * unresolved comments server-side; this panel only creates/lists/resolves
 * them.
 */
export const PresentationComments = ({
  conversationId,
  linkId,
  slideCount,
}: {
  conversationId: string;
  linkId: string;
  slideCount: number;
}) => {
  const { t } = useTranslation();
  const [comments, setComments] = useState<PresentationComment[]>([]);
  const [slideIndex, setSlideIndex] = useState(0);
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setComments(await listPresentationComments(conversationId, linkId));
    } catch {
      setError(t('Could not load comments.'));
    }
  }, [conversationId, linkId, t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const submit = async () => {
    if (!body.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createPresentationComment(conversationId, linkId, {
        slide_index: slideIndex,
        body: body.trim(),
      });
      setBody('');
      await reload();
    } catch {
      setError(t('Could not add the comment.'));
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (commentId: string) => {
    try {
      await resolvePresentationComment(conversationId, linkId, commentId);
      await reload();
    } catch {
      setError(t('Could not resolve the comment.'));
    }
  };

  const unresolved = comments.filter((c) => !c.resolved);

  return (
    <Box
      $direction="column"
      $gap="8px"
      $padding={{ all: '12px' }}
      $css="border-top: 1px solid var(--c--globals--colors--border-default);"
    >
      <Text $weight="600" $size="sm">
        {t('Comments')}
      </Text>

      {comments.length === 0 && (
        <Text $theme="neutral" $variation="secondary" $size="sm">
          {t('Pin feedback to a slide, then ask the assistant to rework it.')}
        </Text>
      )}

      {comments.map((comment) => (
        <Box
          key={comment.id}
          $direction="row"
          $align="center"
          $gap="8px"
          $css={comment.resolved ? 'opacity: 0.6;' : ''}
        >
          <Box $direction="column" $flex={1} $css="min-width: 0;">
            <Text $size="sm" $weight="600">
              {t('Slide {{n}}', { n: comment.slide_index + 1 })}
              {comment.field ? ` · ${comment.field}` : ''}
            </Text>
            <Text $size="sm" $css="overflow-wrap: anywhere;">
              {comment.body}
            </Text>
          </Box>
          {comment.resolved ? (
            <Icon iconName="check_circle" $theme="success" $size="sm" />
          ) : (
            <Button
              size="nano"
              color="neutral"
              variant="tertiary"
              onClick={() => {
                void resolve(comment.id);
              }}
              aria-label={t('Resolve comment')}
              icon={<Icon iconName="check" $theme="inherit" $size="sm" />}
            />
          )}
        </Box>
      ))}

      <Box $direction="row" $gap="8px" $align="center" $wrap="wrap">
        <Box
          as="select"
          value={slideIndex}
          onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
            setSlideIndex(Number(e.target.value))
          }
          aria-label={t('Slide to comment on')}
          $css="padding: 4px 8px; border-radius: 4px; border: 1px solid var(--c--globals--colors--border-default);"
        >
          {Array.from({ length: slideCount }, (_, i) => (
            <option key={i} value={i}>
              {t('Slide {{n}}', { n: i + 1 })}
            </option>
          ))}
        </Box>
        <Box
          as="input"
          type="text"
          value={body}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            setBody(e.target.value)
          }
          placeholder={t('Feedback for this slide…')}
          aria-label={t('Comment text')}
          $css="flex: 1; min-width: 160px; padding: 4px 8px; border-radius: 4px; border: 1px solid var(--c--globals--colors--border-default);"
        />
        <Button
          size="small"
          color="brand"
          variant="secondary"
          disabled={busy || !body.trim()}
          onClick={() => {
            void submit();
          }}
        >
          {t('Add')}
        </Button>
      </Box>

      {error && (
        <Text $theme="danger" $size="sm">
          {error}
        </Text>
      )}

      {unresolved.length > 0 && (
        <Text $theme="neutral" $variation="secondary" $size="sm">
          {t(
            '{{count}} unresolved comment(s). Ask the assistant to rework the deck to apply them.',
            { count: unresolved.length },
          )}
        </Text>
      )}
    </Box>
  );
};
