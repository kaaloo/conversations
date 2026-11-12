import { APIError, errorCauses, fetchAPI } from '@/api';

/** A version snapshot of a sidecar deck (slides-loop POC, P5). */
export interface PresentationVersion {
  id: string;
  number: number;
  source: 'generated' | 'rework' | 'restore';
  slide_count: number;
  created_at: string;
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
