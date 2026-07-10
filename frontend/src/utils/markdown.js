// marked + highlight.js 配置 — Markdown 渲染工具

import { marked } from 'marked'
import hljs from 'highlight.js'
import 'highlight.js/styles/github-dark.css'

let _configured = false

/**
 * 配置 marked 实例：GFM 模式、代码高亮、表格增强
 * 幂等调用，全局只配置一次
 */
export function configureMarked() {
  if (_configured) return
  _configured = true

  marked.setOptions({
    gfm: true,
    breaks: true,
  })

  const renderer = {
    /**
     * 代码块：使用 highlight.js 高亮，自动检测语言
     */
    code({ text, lang }) {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      let highlighted
      try {
        highlighted = hljs.highlight(text, { language }).value
      } catch {
        highlighted = hljs.highlightAuto(text).value
      }
      return (
        `<pre class="code-block-wrapper"><code class="hljs language-${language}">${highlighted}</code></pre>`
      )
    },

    /**
     * 表格：包裹滚动容器以支持响应式
     */
    table({ header, body }) {
      return (
        `<div class="md-table-wrapper">` +
        `<table class="md-table">` +
        `<thead>${header}</thead>` +
        `<tbody>${body}</tbody>` +
        `</table></div>`
      )
    },

    /**
     * 标题：添加锚点 id
     */
    heading({ text, depth }) {
      const id = text
        .toLowerCase()
        .replace(/<[^>]*>/g, '')
        .replace(/[^\w\u4e00-\u9fff]+/g, '-')
        .replace(/^-+|-+$/g, '')
      return `<h${depth} id="${id}" class="md-heading">${text}</h${depth}>`
    },

    /**
     * 链接：外部链接新窗口打开
     */
    link({ href, title, text }) {
      const titleAttr = title ? ` title="${title}"` : ''
      return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`
    },
  }

  marked.use({ renderer })
}

/**
 * 渲染 Markdown 文本为 HTML
 * @param {string} text - Markdown 原文
 * @returns {string} HTML 字符串
 */
export function renderMarkdown(text) {
  if (!text) return ''
  configureMarked()
  try {
    const result = marked.parse(text)
    // marked.parse 可能返回 string | Promise<string>，确保返回 string
    if (result instanceof Promise) {
      // 同步解析不应返回 Promise，但做防御处理
      return ''
    }
    return result
  } catch {
    // 解析失败时返回转义后的原文
    return `<pre>${escapeHtml(text)}</pre>`
  }
}

/**
 * HTML 转义工具
 */
function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
