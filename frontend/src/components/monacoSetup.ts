let setupPromise: Promise<void> | null = null

export const DEWATCH_MONACO_THEME = 'dewatch-dark'

export function registerDeWatchMonacoTheme(monaco: typeof import('monaco-editor')): void {
  monaco.editor.defineTheme(DEWATCH_MONACO_THEME, {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment', foreground: '6E7E91', fontStyle: 'italic' },
      { token: 'keyword', foreground: '7DD3FC' },
      { token: 'string', foreground: '86EFAC' },
      { token: 'number', foreground: 'FDE68A' },
      { token: 'type', foreground: 'A5B4FC' },
      { token: 'function', foreground: '93C5FD' },
    ],
    colors: {
      'editor.background': '#0D1219',
      'editor.foreground': '#E6EDF3',
      'editorLineNumber.foreground': '#475569',
      'editorLineNumber.activeForeground': '#94A3B8',
      'editor.lineHighlightBackground': '#161E2988',
      'editor.lineHighlightBorder': '#222C3A',
      'editor.selectionBackground': '#1D4ED84D',
      'editor.inactiveSelectionBackground': '#1E293B80',
      'editorCursor.foreground': '#38BDF8',
      'editorIndentGuide.background1': '#1E293B',
      'editorIndentGuide.activeBackground1': '#334155',
      'editorGutter.background': '#0D1219',
      'editorWidget.background': '#111720',
      'editorWidget.border': '#222C3A',
    },
  })
}

export async function ensureLocalMonaco(): Promise<void> {
  if (typeof window === 'undefined') return
  if (setupPromise) return setupPromise
  setupPromise = (async () => {
    const [
      { loader },
      monaco,
      { default: EditorWorker },
      { default: JsonWorker },
      { default: CssWorker },
      { default: HtmlWorker },
      { default: TsWorker },
    ] = await Promise.all([
      import('@monaco-editor/react'),
      import('monaco-editor'),
      import('monaco-editor/editor/editor.worker.js?worker'),
      import('monaco-editor/language/json/json.worker.js?worker'),
      import('monaco-editor/language/css/css.worker.js?worker'),
      import('monaco-editor/language/html/html.worker.js?worker'),
      import('monaco-editor/language/typescript/ts.worker.js?worker'),
    ])
    const globalScope = globalThis as typeof globalThis & {
      MonacoEnvironment?: { getWorker: (_moduleId: string, label: string) => Worker }
    }
    globalScope.MonacoEnvironment = {
      getWorker(_moduleId: string, label: string) {
        if (label === 'json') return new JsonWorker()
        if (label === 'css' || label === 'scss' || label === 'less') return new CssWorker()
        if (label === 'html' || label === 'handlebars' || label === 'razor') return new HtmlWorker()
        if (label === 'typescript' || label === 'javascript') return new TsWorker()
        return new EditorWorker()
      },
    }
    registerDeWatchMonacoTheme(monaco)
    loader.config({ monaco })
  })()
  return setupPromise
}
