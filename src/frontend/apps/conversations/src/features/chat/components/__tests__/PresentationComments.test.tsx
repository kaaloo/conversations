import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PresentationComments } from '../PresentationComments';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

const listComments = vi.fn();
const createComment = vi.fn();
const resolveComment = vi.fn();

vi.mock('@/features/chat/api/presentationComments', () => ({
  listPresentationComments: (...args: unknown[]) => listComments(...args),
  createPresentationComment: (...args: unknown[]) => createComment(...args),
  resolvePresentationComment: (...args: unknown[]) => resolveComment(...args),
}));

const COMMENT = {
  id: 'c-1',
  slide_index: 1,
  field: '',
  body: 'shorten this slide',
  resolved: false,
  created_at: '2026-11-12T10:00:00Z',
};

const renderPanel = () =>
  render(
    <PresentationComments
      conversationId="conv-1"
      linkId="link-1"
      slideCount={3}
    />,
  );

describe('PresentationComments', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listComments.mockResolvedValue([]);
  });

  it('lists existing comments with their slide anchor', async () => {
    listComments.mockResolvedValue([COMMENT]);
    renderPanel();

    expect(await screen.findByText('shorten this slide')).toBeInTheDocument();
    expect(screen.getAllByText('Slide {{n}}').length).toBeGreaterThan(0);
  });

  it('creates a comment for the selected slide', async () => {
    createComment.mockResolvedValue({ ...COMMENT, id: 'c-2' });
    renderPanel();
    await waitFor(() => expect(listComments).toHaveBeenCalled());

    await userEvent.type(
      screen.getByLabelText('Comment text'),
      'add a chart here',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() =>
      expect(createComment).toHaveBeenCalledWith('conv-1', 'link-1', {
        slide_index: 0,
        body: 'add a chart here',
      }),
    );
  });

  it('does not submit an empty comment', async () => {
    renderPanel();
    await waitFor(() => expect(listComments).toHaveBeenCalled());

    expect(screen.getByRole('button', { name: 'Add' })).toBeDisabled();
    expect(createComment).not.toHaveBeenCalled();
  });

  it('resolves an unresolved comment', async () => {
    listComments.mockResolvedValue([COMMENT]);
    resolveComment.mockResolvedValue({ ...COMMENT, resolved: true });
    renderPanel();

    await screen.findByText('shorten this slide');
    await userEvent.click(screen.getByLabelText('Resolve comment'));

    await waitFor(() =>
      expect(resolveComment).toHaveBeenCalledWith('conv-1', 'link-1', 'c-1'),
    );
  });
});
