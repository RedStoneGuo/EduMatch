// edu-material-harvest-dsh: 高校公开资料采集 skill for the DeepSeek Harness.
//
// A Cordis plugin that registers one skill provider into the HOST layer of the
// `ctx.skills` registry, so every agent preset's scope chain merges this skill.
// The skill body lives in `../skills/edu-material-harvest/SKILL.md` inside this
// package; the provider locates it from `import.meta.url` (an assembly fact of
// this package, never user config) and loads the body on demand.
//
// The provider protocol mirrors @deepseek-ai/dsh-skill-filesystem:
//   - list()  discovers directory-bundle candidates (name/description from
//     YAML frontmatter, body left unread until requested)
//   - get()   parses the winning candidate's SKILL.md and returns the full
//     definition with a directory resource base for relative references
//
// @module edu-material-harvest-dsh
import { readdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const name = 'edu-material-harvest-dsh'
const inject = ['skills']

/** Registry precedence for packaged skill providers: ranks below the local bundled root. */
const PACKAGED_SKILL_RANK = 550

/** The source bucket these skills advertise under (prompt-visible metadata). */
const SOURCE = 'custom'

/**
 * Parse the YAML frontmatter block of a SKILL.md into metadata plus body.
 * Handles the scalar shapes skill discovery consumes — plain `key: value`,
 * quoted scalars, and block scalars (`|` literal / `>` folded, with optional
 * chomping/indent indicators), which many SKILL.md files use for a long
 * `description`. Richer metadata passes through verbatim.
 * @param text - the raw skill file contents.
 * @returns parsed metadata object and the markdown body after the block, or
 *   null when the file has no frontmatter block at all.
 */
function parseFrontmatter(text) {
  if (!text.startsWith('---')) return null
  const end = text.indexOf('\n---', 3)
  if (end === -1) return null
  const block = text.slice(3, end)
  const body = text.slice(end + 4).replace(/^\n+/, '')

  const metadata = {}
  const lines = block.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const match = /^([A-Za-z][\w-]*):[ \t]*(.*)$/.exec(lines[i])
    if (!match) continue
    const key = match[1]
    let value = match[2].trim()

    const blockScalar = /^([|>])[+-]?\d*$/.exec(value)
    if (blockScalar) {
      // Collect following lines that are more indented than the key.
      const collected = []
      while (i + 1 < lines.length) {
        const next = lines[i + 1]
        if (next.trim() === '') {
          collected.push('')
          i++
          continue
        }
        if (!/^[ \t]/.test(next)) break // dedent to the key level ends the block
        collected.push(next.replace(/^[ \t]+/, ''))
        i++
      }
      while (collected.length > 0 && collected[collected.length - 1] === '') {
        collected.pop()
      }
      value = blockScalar[1] === '|' ? collected.join('\n') : collected.join(' ')
    } else if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    metadata[key] = value
  }
  return { metadata, body }
}

/** Collapse whitespace so a multi-line description reads as one catalog line. */
function oneLine(text) {
  return String(text ?? '').replace(/\s+/g, ' ').trim()
}

/**
 * Read and parse one skill directory's SKILL.md.
 * @param skillFile - absolute path to the SKILL.md file.
 * @param signal - optional cancellation; aborts the read.
 * @returns the parsed skill record, or undefined when the file vanished.
 */
async function parseSkillFile(skillFile, signal) {
  let text
  try {
    text = await readFile(skillFile, 'utf8')
  } catch {
    return undefined
  }
  if (signal?.aborted) return undefined
  const parsed = parseFrontmatter(text)
  if (parsed === null) return undefined
  return {
    name: parsed.metadata.name ?? '',
    description: oneLine(parsed.metadata.description),
    whenToUse: parsed.metadata.whenToUse,
    metadata: parsed.metadata,
    content: parsed.body
  }
}

/**
 * Discover packaged skill candidates by scanning the package's `skills/`
 * directory: one subdirectory per skill, each carrying a SKILL.md.
 * @param skillsRoot - absolute path to this package's skills directory.
 * @param signal - optional cancellation.
 * @returns the candidate list.
 */
async function discoverCandidates(skillsRoot, signal) {
  let entries
  try {
    entries = await readdir(skillsRoot, { withFileTypes: true })
  } catch {
    return []
  }
  const candidates = []
  for (const entry of entries) {
    if (signal?.aborted) break
    if (!entry.isDirectory()) continue
    const skillDir = join(skillsRoot, entry.name)
    const skillFile = join(skillDir, 'SKILL.md')
    const parsed = await parseSkillFile(skillFile, signal)
    if (parsed === undefined) continue
    candidates.push({
      name: parsed.name,
      description: parsed.description,
      ...(parsed.whenToUse !== undefined ? { whenToUse: parsed.whenToUse } : {}),
      invocation: { modelInvocable: true, userInvocable: true },
      source: SOURCE,
      provider: name,
      rank: PACKAGED_SKILL_RANK,
      locator: skillDir,
      path: skillFile,
      ...(Object.keys(parsed.metadata).length > 0 ? { metadata: parsed.metadata } : {})
    })
  }
  return candidates
}

/** Register the packaged skill provider on `ctx.skills`. */
function apply(ctx) {
  const skillsRoot = join(dirname(fileURLToPath(import.meta.url)), '..', 'skills')
  ctx.skills.registerProvider((control) => ({
    name,
    async list(options) {
      return discoverCandidates(skillsRoot, options.signal)
    },
    async get(candidate, options) {
      const parsed = await parseSkillFile(candidate.path, options.signal)
      if (parsed === undefined) return undefined
      return {
        name: parsed.name,
        description: parsed.description,
        ...(parsed.whenToUse !== undefined ? { whenToUse: parsed.whenToUse } : {}),
        invocation: { modelInvocable: true, userInvocable: true },
        source: SOURCE,
        provider: name,
        resourceBase: { kind: 'directory', path: candidate.locator },
        path: candidate.path,
        ...(Object.keys(parsed.metadata).length > 0 ? { metadata: parsed.metadata } : {}),
        content: parsed.content
      }
    }
  }))
}

export { apply, name, inject }
export default { apply, name, inject }
