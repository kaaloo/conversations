import { APIError, errorCauses, fetchAPI } from '@/api';

/** A version snapshot of a sidecar deck (slides-loop POC, P5). */
export interface PresentationVersion {
  id: string;
  number: number;
  source: 'generated' | 'rework' | 'restore';
  slide_count: number;
  created_at: string;
  /** Set on a restore when the sidecar kept slides added after the snapshot. */
  note?: string;
}

const versionsUrl = (conversationId: string, linkId: string) =>
  `chats/${conversationId}/presentations/${linkId}/versions/`;

export const listPresentationVersions = async (
  conversationId: string,
  linkId: string,
): Promise<PresentationVersion[]> => {
  const response = await fetchAPI(versionsUrl(conversationId, linkId));
  if (!response.ok) {
    throw new APIError(
      'Failed to load deck versions',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<PresentationVersion[]>;
};

export const restorePresentationVersion = async (
  conversationId: string,
  linkId: string,
  number: number,
): Promise<PresentationVersion> => {
  const response = await fetchAPI(
    `${versionsUrl(conversationId, linkId)}${number}/restore/`,
    { method: 'POST' },
  );
  if (!response.ok) {
    throw new APIError(
      'Failed to restore deck version',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<PresentationVersion>;
};

/** Fetch a fresh export URL for the current deck (always up to date). */
export const exportPresentation = async (
  conversationId: string,
  linkId: string,
): Promise<string | null> => {
  const response = await fetchAPI(
    `chats/${conversationId}/presentations/${linkId}/export/`,
  );
  if (!response.ok) {
    throw new APIError('Failed to export deck', await errorCauses(response));
  }
  const data = (await response.json()) as { download_url: string | null };
  return data.download_url;
};
