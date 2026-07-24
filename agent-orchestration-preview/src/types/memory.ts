import type { ID, ISODateTime } from './common';

/** 知识库 / 向量库 —— 对齐 F3 长期记忆 / RAG */
export interface KnowledgeBase {
  kb_id: ID;
  name: string;
  /** 嵌入模型（如 text-embedding-3-small） */
  embedding_model: string;
  /** 向量库（如 Chroma / pgvector） */
  vector_store: string;
  doc_count: number;
  updated_at: ISODateTime;
}
