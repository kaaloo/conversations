import { parsePresentationCard } from '../presentationCard';

const CARD = {
  presentation_id: '11111111-1111-1111-1111-111111111111',
  link_id: '22222222-2222-2222-2222-222222222222',
  title: 'A Deck',
  slide_count: 4,
  editor_url: 'http://localhost:5001/presentation?id=11111111',
  download_url: 'http://localhost:5001/app_data/exports/deck.pptx',
};

describe('parsePresentationCard', () => {
  it('parses a well-formed card', () => {
    expect(parsePresentationCard({ presentation: CARD })).toEqual({
      presentationId: CARD.presentation_id,
      linkId: CARD.link_id,
      title: CARD.title,
      slideCount: 4,
      editorUrl: CARD.editor_url,
      downloadUrl: CARD.download_url,
    });
  });

  it('accepts a null download url', () => {
    const parsed = parsePresentationCard({
      presentation: { ...CARD, download_url: null },
    });
    expect(parsed?.downloadUrl).toBeNull();
  });

  it.each([
    ['missing presentation key', {}],
    ['null output', null],
    ['string output', 'presentation'],
    ['non-record presentation', { presentation: 'x' }],
    ['missing title', { presentation: { ...CARD, title: undefined } }],
    ['empty title', { presentation: { ...CARD, title: '' } }],
    ['non-integer slide count', { presentation: { ...CARD, slide_count: 1.5 } }],
    ['negative slide count', { presentation: { ...CARD, slide_count: -1 } }],
    ['javascript editor url', { presentation: { ...CARD, editor_url: 'javascript:alert(1)' } }],
    ['relative editor url', { presentation: { ...CARD, editor_url: '/presentation?id=1' } }],
    ['javascript download url', { presentation: { ...CARD, download_url: 'javascript:alert(1)' } }],
    ['missing link id', { presentation: { ...CARD, link_id: undefined } }],
  ])('rejects %s', (_label, output) => {
    expect(parsePresentationCard(output)).toBeNull();
  });

  it('rejects over-long text', () => {
    expect(
      parsePresentationCard({ presentation: { ...CARD, title: 'x'.repeat(301) } }),
    ).toBeNull();
  });
});
