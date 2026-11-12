import { expect, test } from '@playwright/test';

import { overrideConfig } from './common';

/**
 * Deck-card UI for the slides-loop POC (P6).
 *
 * The conversation API is mocked so the card renders without a live sidecar:
 * this verifies the in-chat deck card, the inline (no-new-tab) editor toggle,
 * and the comments/versions panels. The full generate→edit→rework loop against
 * a real sidecar is covered by the P1 spike and the backend/frontend unit
 * suites; it needs the sidecar container and a tool-calling LLM, which the
 * default e2e stack does not run.
 */

const CONVERSATION_ID = '11111111-1111-1111-1111-111111111111';
const LINK_ID = '22222222-2222-2222-2222-222222222222';

const PRESENTATION_OUTPUT = {
  presentation: {
    presentation_id: '33333333-3333-3333-3333-333333333333',
    link_id: LINK_ID,
    title: 'Sobriété énergétique',
    slide_count: 4,
    editor_url: 'http://localhost:5001/presentation?id=33333333',
    download_url: 'http://localhost:5001/app_data/exports/deck.pptx',
  },
};

const conversationWithDeck = {
  id: CONVERSATION_ID,
  title: 'Deck conversation',
  created_at: '2026-11-12T10:00:00Z',
  updated_at: '2026-11-12T10:00:00Z',
  is_streaming: false,
  messages: [
    {
      id: 'user-1',
      role: 'user',
      parts: [{ type: 'text', text: 'Make a deck about energy sobriety' }],
    },
    {
      id: 'assistant-1',
      role: 'assistant',
      parts: [
        {
          type: 'tool-generate_presentation_sidecar',
          toolCallId: 'call-1',
          state: 'output-available',
          input: { brief: 'energy sobriety' },
          output: PRESENTATION_OUTPUT,
        },
      ],
    },
  ],
};

test.describe('Presentation deck card', () => {
  test.beforeEach(async ({ page }) => {
    await overrideConfig(page, {
      FEATURE_FLAGS: {
        'presenton-sidecar': 'enabled',
      },
    });
    await page.route(`**/api/v1.0/chats/${CONVERSATION_ID}/`, async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({ json: conversationWithDeck });
      } else {
        await route.continue();
      }
    });
    await page.route(
      `**/api/v1.0/chats/${CONVERSATION_ID}/presentations/${LINK_ID}/comments/`,
      async (route) => {
        await route.fulfill({ json: [] });
      },
    );
    await page.route(
      `**/api/v1.0/chats/${CONVERSATION_ID}/presentations/${LINK_ID}/versions/`,
      async (route) => {
        await route.fulfill({ json: [] });
      },
    );
  });

  test('renders the deck card with its actions', async ({ page }) => {
    await page.goto(`/chat/${CONVERSATION_ID}`);

    await expect(page.getByText('Sobriété énergétique')).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Edit slides' }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Download PPTX' }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: 'Comments' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Versions' })).toBeVisible();
  });

  test('opens the editor inline, not in a new tab', async ({ page }) => {
    await page.goto(`/chat/${CONVERSATION_ID}`);

    await page.getByRole('button', { name: 'Edit slides' }).click();

    const frame = page.locator('iframe[title*="Slide editor"]');
    await expect(frame).toBeVisible();
    await expect(frame).toHaveAttribute(
      'src',
      PRESENTATION_OUTPUT.presentation.editor_url,
    );
    // Inline embed: no target=_blank (which would open a new tab).
    await expect(frame).not.toHaveAttribute('target', '_blank');
  });

  test('opens the comments and versions panels', async ({ page }) => {
    await page.goto(`/chat/${CONVERSATION_ID}`);

    await page.getByRole('button', { name: 'Comments' }).click();
    await expect(
      page.getByText(
        'Pin feedback to a slide, then ask the assistant to rework it.',
      ),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Versions' }).click();
    await expect(page.getByText('No versions recorded yet.')).toBeVisible();
  });
});
