import { Button } from '@gouvfr-lasuite/cunningham-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Box, Icon, Text } from '@/components';
import {
  type PresentationVersion,
  listPresentationVersions,
  restorePresentationVersion,
} from '@/features/chat/api/presentationVersions';

/**
 * Version history for a sidecar deck (slides-loop POC, P5).
 *
 * Lists the recorded snapshots (generation, rework, restore) and lets the
 * user restore one. Restoring re-applies the snapshot to the live deck and
 * records a new version; the deck card's editor reflects it on reload.
 */
export const PresentationVersions = ({
  conversationId,
  linkId,
}: {
  conversationId: string;
  linkId: string;
}) => {
  const { t } = useTranslation();
  const [versions, setVersions] = useState<PresentationVersion[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setVersions(await listPresentationVersions(conversationId, linkId));
    } catch {
      setError(t('Could not load versions.'));
    }
  }, [conversationId, linkId, t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const restore = async (number: number) => {
    setBusy(true);
    setError(null);
    try {
      await restorePresentationVersion(conversationId, linkId, number);
      await reload();
    } catch {
      setError(t('Could not restore this version.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Box
      $direction="column"
      $gap="8px"
      $padding={{ all: '12px' }}
      $css="border-top: 1px solid var(--c--globals--colors--border-default);"
    >
      <Text $weight="600" $size="sm">
        {t('Version history')}
      </Text>

      {versions.length === 0 && (
        <Text $theme="neutral" $variation="secondary" $size="sm">
          {t('No versions recorded yet.')}
        </Text>
      )}

      {versions.map((version, idx) => (
        <Box key={version.id} $direction="row" $align="center" $gap="8px">
          <Box $direction="column" $flex={1} $css="min-width: 0;">
            <Text $size="sm" $weight="600">
              {t('Version {{n}}', { n: version.number })}
              {idx === 0 ? ` · ${t('current')}` : ''}
            </Text>
            <Text $theme="neutral" $variation="secondary" $size="sm">
              {t('{{source}} · {{count}} slides', {
                source: version.source,
                count: version.slide_count,
              })}
            </Text>
          </Box>
          {idx !== 0 && (
            <Button
              size="nano"
              color="neutral"
              variant="tertiary"
              disabled={busy}
              onClick={() => {
                void restore(version.number);
              }}
              aria-label={t('Restore version {{n}}', { n: version.number })}
              icon={<Icon iconName="history" $theme="inherit" $size="sm" />}
            />
          )}
        </Box>
      ))}

      {error && (
        <Text $theme="danger" $size="sm">
          {error}
        </Text>
      )}
    </Box>
  );
};
