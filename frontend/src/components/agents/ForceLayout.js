/**
 * TidyTreeLayout - 横向 tidy tree 布局算法
 *
 * 参考 d3-hierarchy 的 Reingold-Tilford 算法:
 *   1. BFS 从根节点给每个节点赋 layer (列号)
 *   2. 同父节点的所有子节点垂直堆叠
 *   3. 父节点 y 坐标 = 子节点 y 坐标的中点
 *   4. 叶子节点均匀分布填充高度
 *
 * 不依赖任何第三方库。边通过父子关系自动生成 (parent-child)。
 */
export class ForceLayout {
  constructor(nodes = [], edges = [], width = 1200, height = 600) {
    this.nodes = nodes
    this.edges = edges
    this.width = width
    this.height = height

    this.layerGap = 160   // 父节点 → 子节点的横向间距
    this.nodeSpacing = 50 // 同层节点之间的最小垂直间距
    this.margin = 30
  }

  // ========== 1. 找根节点 ==========
  _findRoot(preferId) {
    // 优先级：security > host > action > 第一个节点
    if (preferId) {
      const match = this.nodes.find(n => n.id === preferId)
      if (match) return match
    }
    const priorities = ['security', 'host', 'action', 'file', 'url']
    for (const p of priorities) {
      const node = this.nodes.find(n => n.type === p)
      if (node) return node
    }
    return this.nodes[0]
  }

  // ========== 2. BFS 构造树结构（基于最短路径） ==========
  _buildTree(preferRootId) {
    if (this.nodes.length === 0) return null

    const root = this._findRoot(preferRootId)
    if (!root) return null

    // 构造邻接表（无向图）
    const adj = new Map()
    this.nodes.forEach(n => adj.set(n.id, new Set()))
    for (const e of this.edges) {
      if (adj.has(e.source) && adj.has(e.target)) {
        adj.get(e.source).add(e.target)
        adj.get(e.target).add(e.source)
      }
    }

    // BFS 赋 layer + parent
    const layerOf = new Map()
    const parentOf = new Map()
    const childrenOf = new Map()
    layerOf.set(root.id, 0)
    parentOf.set(root.id, null)
    childrenOf.set(root.id, [])

    const queue = [root.id]
    const visited = new Set([root.id])

    while (queue.length) {
      const cur = queue.shift()
      const curLayer = layerOf.get(cur)
      for (const nb of adj.get(cur) || []) {
        if (visited.has(nb)) continue
        visited.add(nb)
        layerOf.set(nb, curLayer + 1)
        parentOf.set(nb, cur)
        childrenOf.set(cur, [...(childrenOf.get(cur) || []), nb])
        childrenOf.set(nb, childrenOf.get(nb) || [])
        queue.push(nb)
      }
    }

    // 孤立节点（无连接）放在 root 右侧第一层
    for (const n of this.nodes) {
      if (!visited.has(n.id)) {
        const l = 1
        layerOf.set(n.id, l)
        parentOf.set(n.id, root.id)
        childrenOf.set(root.id, [...(childrenOf.get(root.id) || []), n.id])
        childrenOf.set(n.id, [])
      }
    }

    return { root, layerOf, parentOf, childrenOf }
  }

  // ========== 3. Reingold-Tilford 树布局（简化版） ==========
  // 先把每棵子树垂直尺寸（高度）算出来，再分配 y 坐标
  _layoutTree(tree) {
    const { root, layerOf, parentOf, childrenOf } = tree
    const nodeMap = new Map(this.nodes.map(n => [n.id, n]))

    // 后序遍历：算每棵子树的"高度"（占用的垂直空间 = 节点数 * spacing）
    const subtreeHeight = new Map()
    const measure = (id) => {
      const kids = childrenOf.get(id) || []
      if (kids.length === 0) {
        subtreeHeight.set(id, this.nodeSpacing)
        return this.nodeSpacing
      }
      let total = 0
      for (const k of kids) total += measure(k)
      const h = Math.max(this.nodeSpacing, total)
      subtreeHeight.set(id, h)
      return h
    }
    measure(root.id)

    // 前序遍历：分配 y 坐标（子节点按子树的占用空间叠加）
    const xOf = new Map()
    const yOf = new Map()
    const place = (id, topY) => {
      const layer = layerOf.get(id)
      xOf.set(id, this.margin + layer * this.layerGap)
      const kids = childrenOf.get(id) || []
      if (kids.length === 0) {
        yOf.set(id, topY + this.nodeSpacing / 2)
        return
      }
      // 子节点堆叠
      let cur = topY
      for (const k of kids) {
        const kh = subtreeHeight.get(k)
        place(k, cur)
        cur += kh
      }
      // 父节点 y = 子节点 y 的中点
      const childYs = kids.map(k => yOf.get(k))
      yOf.set(id, (Math.min(...childYs) + Math.max(...childYs)) / 2)
    }
    place(root.id, this.margin)

    // 垂直居中：把整体高度偏移到画布中心
    const totalH = subtreeHeight.get(root.id)
    const offsetY = (this.height - totalH) / 2 - this.margin
    if (offsetY !== 0) {
      for (const id of yOf.keys()) {
        yOf.set(id, yOf.get(id) + offsetY)
      }
    }

    // 应用到节点
    for (const n of this.nodes) {
      n.x = xOf.get(n.id) ?? 0
      n.y = yOf.get(n.id) ?? 0
      n.vx = 0
      n.vy = 0
    }
  }

  // ========== 4. 边转树边（用 parent-child 关系） ==========
  _buildTreeEdges(tree) {
    if (!tree) return []
    const { parentOf, childrenOf } = tree
    const out = []
    for (const [parentId, kids] of childrenOf) {
      for (const kid of kids) {
        out.push({
          id: `${parentId}--${kid}`,
          source: parentId,
          target: kid,
          relation: '关联',
          description: '',
          directed: true,
        })
      }
    }
    return out
  }

  run(preferRootId) {
    const tree = this._buildTree(preferRootId)
    if (!tree) return
    this._layoutTree(tree)
    // 覆盖 this.edges 为树边（仅用于渲染）
    this._treeEdges = this._buildTreeEdges(tree)
  }

  // 下钻：把指定节点设为树的新根重新布局
  setRoot(nodeId) {
    this.run(nodeId)
  }

  addNode(node) {
    this.nodes.push(node)
    // 增量添加：放到根的右侧第一层
    if (this.nodes.length === 1) {
      node.x = this.margin
      node.y = this.height / 2
    } else {
      const tree = this._buildTree()
      if (tree) {
        this._layoutTree(tree)
        this._treeEdges = this._buildTreeEdges(tree)
      }
    }
    node.vx = 0
    node.vy = 0
  }

  addEdge(edge) {
    this.edges.push(edge)
    // 增量添加边后重新布局
    const tree = this._buildTree()
    if (tree) {
      this._layoutTree(tree)
      this._treeEdges = this._buildTreeEdges(tree)
    }
  }

  // 返回布局产生的树边（覆盖原 edges 渲染）
  getTreeEdges() {
    return this._treeEdges || []
  }

  getBounds() {
    if (this.nodes.length === 0) return null
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    for (const n of this.nodes) {
      minX = Math.min(minX, n.x)
      minY = Math.min(minY, n.y)
      maxX = Math.max(maxX, n.x)
      maxY = Math.max(maxY, n.y)
    }
    return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY }
  }
}
