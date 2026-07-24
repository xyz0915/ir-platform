import { useEffect, useState } from 'react';
import { Box, Button, Card, CardContent, Chip, Grid, Stack, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import StorageIcon from '@mui/icons-material/Storage';
import dayjs from 'dayjs';
import { PageHeader } from '@/components/shared/PageHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { getKnowledgeBases } from '@/mocks/memory';
import type { KnowledgeBase } from '@/types';

export function MemoryPage() {
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    getKnowledgeBases().then((res) => {
      if (alive) {
        setKbs(res.data);
        setLoading(false);
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  const addKb = () => {
    const kb: KnowledgeBase = {
      kb_id: `kb-custom-${Date.now()}`,
      name: `新知识库 ${kbs.length + 1}`,
      embedding_model: 'text-embedding-3-small',
      vector_store: 'Chroma',
      doc_count: 0,
      updated_at: new Date().toISOString(),
    };
    setKbs((prev) => [kb, ...prev]);
  };

  return (
    <Box>
      <PageHeader
        title="记忆与 RAG"
        subtitle="知识库 / 向量库概览、嵌入模型与检索增强（F3 / M3，轻量占位）"
        action={
          <Button variant="contained" startIcon={<AddIcon />} onClick={addKb}>
            新建知识库
          </Button>
        }
      />

      {loading ? (
        <EmptyState title="加载中…" />
      ) : (
        <Grid container spacing={2}>
          {kbs.map((kb) => (
            <Grid item xs={12} sm={6} md={4} key={kb.kb_id}>
              <Card sx={{ height: '100%' }}>
                <CardContent>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
                    <StorageIcon color="secondary" />
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, flexGrow: 1 }}>
                      {kb.name}
                    </Typography>
                  </Stack>
                  <Stack spacing={0.5}>
                    <Row label="嵌入模型" value={kb.embedding_model} />
                    <Row label="向量库" value={kb.vector_store} />
                    <Row label="文档数" value={kb.doc_count.toLocaleString()} />
                    <Row label="更新时间" value={dayjs(kb.updated_at).format('MM-DD HH:mm')} />
                  </Stack>
                  <Box sx={{ mt: 1.5 }}>
                    <Chip size="small" color="secondary" variant="outlined" label="RAG 检索增强" />
                  </Box>
                </CardContent>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 1 }}>
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {value}
      </Typography>
    </Box>
  );
}
