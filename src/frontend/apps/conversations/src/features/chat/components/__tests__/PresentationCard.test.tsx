import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { useCunninghamTheme } from '@/cunningham';
import { useChatPreferencesStore } from '@/features/chat/stores/useChatPreferencesStore';
import type { PresentationCardData } from '@/features/chat/utils/presentationCard';

import { PresentationCard } from '../PresentationCard';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

vi.mock('@/utils/useConversationRouteId', () => ({
  useConversationRouteId: () => 'conv-1',
}));

const presentation: PresentationCardData = {
  presentationId: 'deck-1',
  linkId: 'link-1',
  title: 'Sobriété énergétique',
  slideCount: 4,
  editorUrl: 'http://localhost:5001/presentation?id=deck-1',
  downloadUrl: null,
};

describe('PresentationCard editor theming', () => {
  beforeEach(() => {
    useChatPreferencesStore.getState().setThemeModePreference('light');
    useCunninghamTheme.getState().setTheme('dsfr');
  });

  afterEach(() => {
    useCunninghamTheme.getState().setTheme('default');
    useChatPreferencesStore.getState().setThemeModePreference('system');
  });

  it('applies initial theme parameters and updates by origin without reloading', async () => {
    render(<PresentationCard presentation={presentation} />);
    await userEvent.click(screen.getByRole('button', { name: 'Edit slides' }));

    const frame = screen.getByTitle<HTMLIFrameElement>(/Slide editor/);
    const initialUrl = new URL(frame.src);
    expect(initialUrl.searchParams.get('id')).toBe('deck-1');
    expect(initialUrl.searchParams.get('ui_theme')).toBe('dsfr');
    expect(initialUrl.searchParams.get('scheme')).toBe('light');
    expect(initialUrl.searchParams.get('host_origin')).toBe(
      window.location.origin,
    );

    const postMessage = vi.fn();
    Object.defineProperty(frame.contentWindow, 'postMessage', {
      value: postMessage,
      writable: true,
    });

    act(() => {
      useChatPreferencesStore.getState().setThemeModePreference('dark');
    });

    await waitFor(() =>
      expect(postMessage).toHaveBeenCalledWith(
        {
          type: 'presenton:editor-theme',
          theme: 'dsfr',
          scheme: 'dark',
        },
        'http://localhost:5001',
      ),
    );
    expect(frame.src).toBe(initialUrl.toString());

    postMessage.mockClear();
    fireEvent.load(frame);
    await waitFor(() =>
      expect(postMessage).toHaveBeenCalledWith(
        {
          type: 'presenton:editor-theme',
          theme: 'dsfr',
          scheme: 'dark',
        },
        'http://localhost:5001',
      ),
    );
    expect(frame.src).toBe(initialUrl.toString());

    act(() => {
      useCunninghamTheme.getState().setTheme('default');
      useChatPreferencesStore.getState().setThemeModePreference('light');
    });
    await waitFor(() =>
      expect(postMessage).toHaveBeenCalledWith(
        {
          type: 'presenton:editor-theme',
          theme: 'presenton',
          scheme: 'light',
        },
        'http://localhost:5001',
      ),
    );
    expect(frame.src).toBe(initialUrl.toString());

    await userEvent.click(screen.getByRole('button', { name: 'Close editor' }));
    await userEvent.click(screen.getByRole('button', { name: 'Edit slides' }));

    const reopenedFrame = screen.getByTitle<HTMLIFrameElement>(/Slide editor/);
    const reopenedUrl = new URL(reopenedFrame.src);
    expect(reopenedUrl.searchParams.get('ui_theme')).toBe('presenton');
    expect(reopenedUrl.searchParams.get('scheme')).toBe('light');
    expect(reopenedUrl.searchParams.get('id')).toBe('deck-1');
  });
});
