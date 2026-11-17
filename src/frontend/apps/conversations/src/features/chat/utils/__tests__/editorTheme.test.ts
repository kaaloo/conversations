import {
  buildEditorUrl,
  createEditorThemeMessage,
  getEditorOrigin,
  getEditorThemeConfig,
} from '../editorTheme';

describe('editor theme integration', () => {
  it('maps host themes to the embedded editor contract', () => {
    expect(getEditorThemeConfig('dsfr')).toEqual({
      theme: 'dsfr',
      scheme: 'light',
    });
    expect(getEditorThemeConfig('dsfr-dark')).toEqual({
      theme: 'dsfr',
      scheme: 'dark',
    });
    expect(getEditorThemeConfig('default')).toEqual({
      theme: 'presenton',
      scheme: 'light',
    });
    expect(getEditorThemeConfig('dark')).toEqual({
      theme: 'presenton',
      scheme: 'light',
    });
  });

  it('preserves deck and navigation parameters while adding theme configuration', () => {
    const url = new URL(
      buildEditorUrl(
        'http://localhost:5001/presentation?id=deck-1&mode=present&slide=2',
        'dsfr-dark',
        'http://localhost:3000',
      ),
    );

    expect(url.searchParams.get('id')).toBe('deck-1');
    expect(url.searchParams.get('mode')).toBe('present');
    expect(url.searchParams.get('slide')).toBe('2');
    expect(url.searchParams.get('ui_theme')).toBe('dsfr');
    expect(url.searchParams.get('scheme')).toBe('dark');
    expect(url.searchParams.get('host_origin')).toBe('http://localhost:3000');
  });

  it('uses the exact editor origin and message schema', () => {
    expect(
      getEditorOrigin('https://slides.example:5001/presentation?id=deck-1'),
    ).toBe('https://slides.example:5001');
    expect(createEditorThemeMessage('dsfr-dark')).toEqual({
      type: 'presenton:editor-theme',
      theme: 'dsfr',
      scheme: 'dark',
    });
  });
});
