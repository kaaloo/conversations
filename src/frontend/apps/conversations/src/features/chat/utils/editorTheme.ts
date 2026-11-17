import type { Theme } from '@/cunningham/useCunninghamTheme';

export const EDITOR_THEME_MESSAGE_TYPE = 'presenton:editor-theme';

export interface EditorThemeConfig {
  theme: 'presenton' | 'dsfr';
  scheme: 'light' | 'dark';
}

export interface EditorThemeMessage extends EditorThemeConfig {
  type: typeof EDITOR_THEME_MESSAGE_TYPE;
}

export const getEditorThemeConfig = (theme: Theme): EditorThemeConfig => ({
  theme: theme === 'dsfr' || theme === 'dsfr-dark' ? 'dsfr' : 'presenton',
  scheme: theme === 'dsfr-dark' ? 'dark' : 'light',
});

export const buildEditorUrl = (
  editorUrl: string,
  theme: Theme,
  hostOrigin: string,
): string => {
  const url = new URL(editorUrl);
  const config = getEditorThemeConfig(theme);
  url.searchParams.set('ui_theme', config.theme);
  url.searchParams.set('scheme', config.scheme);
  url.searchParams.set('host_origin', hostOrigin);
  return url.toString();
};

export const getEditorOrigin = (editorUrl: string): string =>
  new URL(editorUrl).origin;

export const createEditorThemeMessage = (theme: Theme): EditorThemeMessage => ({
  type: EDITOR_THEME_MESSAGE_TYPE,
  ...getEditorThemeConfig(theme),
});
