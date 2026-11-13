// Генерирует src/styles/tokens.css из replica/design/tokens*.json.
// Запуск: node scripts/tokens.mjs
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const root = new URL('../../replica/design/', import.meta.url)
const dark = JSON.parse(readFileSync(new URL('tokens.json', root), 'utf8'))
const light = JSON.parse(readFileSync(new URL('tokens.light.json', root), 'utf8'))

const vars = (colors) => Object.entries(colors).map(([k, v]) => `  --c-${k}: ${v};`).join('\n')
const css = `/* Сгенерировано scripts/tokens.mjs из replica/design. Не редактировать вручную. */
:root, [data-theme='dark'] {
${vars(dark.color)}
  color-scheme: dark;
}
[data-theme='light'] {
${vars(light.color)}
  color-scheme: light;
}
:root {
  --font-sans: ${dark.font.sans};
  --font-mono: ${dark.font.mono};
${Object.entries(dark.size).map(([k, v]) => `  --size-${k}: ${v}px;`).join('\n')}
  --motion-fast: ${dark.motion.fast};
  --motion-base: ${dark.motion.base};
  --motion-ease: ${dark.motion.ease};
  --shadow-pop: ${dark.shadow.pop};
}
`
writeFileSync(fileURLToPath(new URL('../src/styles/tokens.css', import.meta.url)), css)
console.log('tokens.css written')
