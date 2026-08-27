import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { generateAIAnalysis, getAIAnalysis } from './api';

/** 返回单个标的 AI 分析使用的稳定缓存键。 */
export function aiAnalysisQueryKey(instrumentId: string) {
  return ['ai-analysis', instrumentId] as const;
}

/** 只读取已保存报告，不因打开弹窗产生模型费用。 */
export function useAIAnalysis(instrumentId: string | null) {
  return useQuery({
    queryKey: aiAnalysisQueryKey(instrumentId ?? ''),
    queryFn: () => getAIAnalysis(instrumentId ?? ''),
    enabled: instrumentId !== null,
    retry: false,
  });
}

/** 手动生成成功后直接替换当前标的的页面缓存。 */
export function useGenerateAIAnalysis(instrumentId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => generateAIAnalysis(instrumentId),
    onSuccess: (report) => client.setQueryData(aiAnalysisQueryKey(instrumentId), report),
  });
}
