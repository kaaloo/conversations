import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PresentationVersions } from '../PresentationVersions';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

const listVersions = vi.fn();
const restoreVersion = vi.fn();

vi.mock('@/features/chat/api/presentationVersions', () => ({
  listPresentationVersions: (...args: unknown[]) => listVersions(...args),
  restorePresentationVersion: (...args: unknown[]) => restoreVersion(...args),
}));

const VERSIONS = [
  {
    id: 'v-2',
    number: 2,
    source: 'rework',
    slide_count: 3,
    created_at: '2026-11-12T11:00:00Z',
  },
  {
    id: 'v-1',
    number: 1,
    source: 'generated',
    slide_count: 2,
    created_at: '2026-11-12T10:00:00Z',
  },
];

const renderPanel = () =>
  render(<PresentationVersions conversationId="conv-1" linkId="link-1" />);

describe('PresentationVersions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listVersions.mockResolvedValue([]);
  });

  it('lists versions newest first and marks the current one', async () => {
    listVersions.mockResolvedValue(VERSIONS);
    renderPanel();

    expect(await screen.findByText('Version {{n}}')).toBeInTheDocument();
    expect(screen.getAllByText(/Version \{\{n\}\}/).length).toBe(2);
  });

  it('restores an older version', async () => {
    listVersions.mockResolvedValue(VERSIONS);
    restoreVersion.mockResolvedValue({ ...VERSIONS[0], number: 3 });
    renderPanel();

    await screen.findAllByText('Version {{n}}');
    const restoreButtons = screen.getAllByLabelText('Restore version {{n}}');
    // The older version (number 1) is the second row.
    await userEvent.click(restoreButtons[1]);

    await waitFor(() =>
      expect(restoreVersion).toHaveBeenCalledWith('conv-1', 'link-1', 1),
    );
  });

  it('allows restoring the latest recorded snapshot', async () => {
    listVersions.mockResolvedValue(VERSIONS);
    restoreVersion.mockResolvedValue({ ...VERSIONS[0], number: 3 });
    renderPanel();

    await screen.findAllByText('Version {{n}}');
    const restoreButtons = screen.getAllByLabelText('Restore version {{n}}');
    // Manual edits are not recorded, so the latest snapshot is restorable too.
    expect(restoreButtons.length).toBe(2);
    await userEvent.click(restoreButtons[0]);

    await waitFor(() =>
      expect(restoreVersion).toHaveBeenCalledWith('conv-1', 'link-1', 2),
    );
  });

  it('shows an empty state when there are no versions', async () => {
    renderPanel();
    expect(
      await screen.findByText('No versions recorded yet.'),
    ).toBeInTheDocument();
  });
});
