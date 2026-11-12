import { APIError, errorCauses, fetchAPI } from '@/api';

/** A slide-anchored comment on a sidecar deck (slides-loop POC, P4). */
export interface PresentationComment {
  id: string;
  slide_index: number;
  field: string;
  body: string;
  resolved: boolean;
  created_at: string;
}

const commentsUrl = (conversationId: string, linkId: string) =>
  `chats/${conversationId}/presentations/${linkId}/comments/`;

export const listPresentationComments = async (
  conversationId: string,
  linkId: string,
): Promise<PresentationComment[]> => {
  const response = await fetchAPI(commentsUrl(conversationId, linkId));
  if (!response.ok) {
    throw new APIError(
      'Failed to load deck comments',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<PresentationComment[]>;
};

export const createPresentationComment = async (
  conversationId: string,
  linkId: string,
  comment: { slide_index: number; field?: string; body: string },
): Promise<PresentationComment> => {
  const response = await fetchAPI(commentsUrl(conversationId, linkId), {
    method: 'POST',
    body: JSON.stringify(comment),
  });
  if (!response.ok) {
    throw new APIError(
      'Failed to add deck comment',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<PresentationComment>;
};

export const resolvePresentationComment = async (
  conversationId: string,
  linkId: string,
  commentId: string,
): Promise<PresentationComment> => {
  const response = await fetchAPI(
    `${commentsUrl(conversationId, linkId)}${commentId}/resolve/`,
    { method: 'POST' },
  );
  if (!response.ok) {
    throw new APIError(
      'Failed to resolve deck comment',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<PresentationComment>;
};
