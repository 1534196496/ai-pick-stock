import { useState, type FormEvent } from 'react';

import { ApiClientError } from '../../shared/api/client';
import { useModalDialog } from '../../shared/ui/useModalDialog';
import type {
  MarketDataSchedule,
  SyncJobType,
  UpdateMarketDataScheduleInput,
} from './api';
import {
  useManualMarketDataSync,
  useMarketDataSchedule,
  useMarketDataStatus,
  useUpdateMarketDataSchedule,
} from './hooks';
import './market-data.css';

interface MarketDataDialogProps {
  onClose: () => void;
}

const ALL_JOB_TYPES: SyncJobType[] = [
  'STOCK_PRICES',
  'FUND_ESTIMATED_NAV',
  'FUND_OFFICIAL_NAV',
  'INSTRUMENT_MASTER',
];

const JOB_LABEL: Record<SyncJobType, string> = {
  STOCK_PRICES: '股票行情',
  FUND_ESTIMATED_NAV: '基金盘中估算',
  FUND_OFFICIAL_NAV: '基金官方净值',
  INSTRUMENT_MASTER: '股票与基金标的库',
};

/** 管理后台行情 Job 的频率、每日窗口和人工触发。 */
export function MarketDataDialog({ onClose }: MarketDataDialogProps) {
  const { dialogRef, closeDialog } = useModalDialog(onClose);
  const schedule = useMarketDataSchedule();
  const status = useMarketDataStatus();
  const manualSync = useManualMarketDataSync();
  const visibleJobs = manualSync.data?.jobs ?? status.data?.jobs ?? [];

  /** 立即执行选定任务，并保留对话框展示最终结果。 */
  async function runJobs(jobTypes: SyncJobType[]) {
    try {
      await manualSync.mutateAsync(jobTypes);
    } catch {
      // 请求错误由对话框中的稳定错误提示展示。
    }
  }

  return (
    <dialog
      className="market-data-dialog"
      ref={dialogRef}
      aria-labelledby="market-data-dialog-title"
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
    >
      <header className="dialog-heading">
        <div>
          <p className="eyebrow">后台任务</p>
          <h2 id="market-data-dialog-title">行情刷新</h2>
        </div>
        <button className="text-button" type="button" onClick={closeDialog}>关闭</button>
      </header>

      {schedule.isPending && <p className="market-data-status" role="status">正在读取任务配置…</p>}
      {schedule.isError && <p className="form-error" role="alert">任务配置读取失败，请稍后重试。</p>}
      {schedule.data !== undefined && (
        <ScheduleForm key={schedule.data.version} schedule={schedule.data} />
      )}

      <section className="manual-sync" aria-labelledby="manual-sync-title">
        <div>
          <h3 id="manual-sync-title">立即执行</h3>
          <p>直接运行后台 Job，完成后持仓和自选行情会重新读取。</p>
        </div>
        <div className="manual-sync__actions">
          {ALL_JOB_TYPES.map((jobType) => (
            <button
              className="secondary-button"
              key={jobType}
              type="button"
              disabled={manualSync.isPending || schedule.data?.liveSyncEnabled === false}
              onClick={() => void runJobs([jobType])}
            >
              {JOB_LABEL[jobType]}
            </button>
          ))}
          <button
            className="primary-button"
            type="button"
            disabled={manualSync.isPending || schedule.data?.liveSyncEnabled === false}
            onClick={() => void runJobs(ALL_JOB_TYPES)}
          >
            {manualSync.isPending ? '正在刷新…' : '全部刷新'}
          </button>
        </div>
        {schedule.data?.liveSyncEnabled === false && (
          <p className="market-data-note" role="status">服务器外部行情同步尚未启用，部署配置开启后才能执行。</p>
        )}
        {manualSync.error !== null && (
          <p className="form-error" role="alert">
            {manualSync.error instanceof ApiClientError
              ? manualSync.error.message
              : '手动刷新失败，请稍后重试。'}
          </p>
        )}
      </section>

      <section className="job-history" aria-labelledby="job-history-title">
        <h3 id="job-history-title">最近执行</h3>
        {visibleJobs.length === 0 ? (
          <p className="market-data-status">暂无执行记录</p>
        ) : (
          <ul>
            {visibleJobs.map((job) => (
              <li key={job.jobType}>
                <span><strong>{JOB_LABEL[job.jobType]}</strong>{formatFinishedAt(job.finishedAt)}</span>
                <span className={`job-result job-result--${job.status.toLowerCase()}`}>
                  {job.status === 'SUCCEEDED' ? '成功' : job.status === 'PARTIAL' ? '部分成功' : job.status === 'RUNNING' ? '执行中' : '失败'}
                  {' · '}{job.succeededCount} 条
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </dialog>
  );
}

interface ScheduleFormProps {
  schedule: MarketDataSchedule;
}

/** 编辑并保存 Worker 实际采用的调度参数。 */
function ScheduleForm({ schedule }: ScheduleFormProps) {
  const update = useUpdateMarketDataSchedule();
  const [form, setForm] = useState<UpdateMarketDataScheduleInput>({
    stockRefreshSeconds: schedule.stockRefreshSeconds,
    fundEstimateRefreshSeconds: schedule.fundEstimateRefreshSeconds,
    officialNavRefreshSeconds: schedule.officialNavRefreshSeconds,
    officialNavWindowStart: normalizeTime(schedule.officialNavWindowStart),
    officialNavWindowEnd: normalizeTime(schedule.officialNavWindowEnd),
    instrumentSyncTime: normalizeTime(schedule.instrumentSyncTime),
  });

  /** 保存后端调度参数，Worker 会根据版本号自动重新排期。 */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await update.mutateAsync(form);
    } catch {
      // 保留当前输入，错误信息紧邻保存按钮展示。
    }
  }

  return (
    <form className="schedule-form" onSubmit={(event) => void submit(event)}>
      <div className="schedule-form__grid">
        <IntervalField label="股票行情" value={form.stockRefreshSeconds} options={[15, 30, 60, 120]} onChange={(value) => setForm({ ...form, stockRefreshSeconds: value })} />
        <IntervalField label="基金盘中估算" value={form.fundEstimateRefreshSeconds} options={[30, 60, 120, 300]} onChange={(value) => setForm({ ...form, fundEstimateRefreshSeconds: value })} />
        <IntervalField label="官方净值检查" value={form.officialNavRefreshSeconds} options={[120, 300, 600, 1800]} onChange={(value) => setForm({ ...form, officialNavRefreshSeconds: value })} />
        <label><span>标的库每日同步</span><input type="time" required value={form.instrumentSyncTime} onChange={(event) => setForm({ ...form, instrumentSyncTime: event.target.value })} /></label>
        <label><span>官方净值开始</span><input type="time" required value={form.officialNavWindowStart} onChange={(event) => setForm({ ...form, officialNavWindowStart: event.target.value })} /></label>
        <label><span>官方净值结束</span><input type="time" required value={form.officialNavWindowEnd} onChange={(event) => setForm({ ...form, officialNavWindowEnd: event.target.value })} /></label>
      </div>
      {!schedule.fundEstimateSyncEnabled && (
        <p className="market-data-note">基金盘中估算自动任务当前被部署配置关闭，频率会保存但暂不自动运行。</p>
      )}
      {update.error !== null && (
        <p className="form-error" role="alert">
          {update.error instanceof ApiClientError ? update.error.message : '保存失败，请稍后重试。'}
        </p>
      )}
      <div className="schedule-form__footer">
        <span>{update.isSuccess ? '已保存，Worker 将在10秒内生效' : `配置版本 ${schedule.version}`}</span>
        <button className="primary-button" disabled={update.isPending} type="submit">
          {update.isPending ? '正在保存…' : '保存任务设置'}
        </button>
      </div>
    </form>
  );
}

interface IntervalFieldProps {
  label: string;
  value: number;
  options: number[];
  onChange: (value: number) => void;
}

/** 使用受控下拉框编辑有限且安全的 Job 秒级频率。 */
function IntervalField({ label, value, options, onChange }: IntervalFieldProps) {
  return (
    <label>
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(Number(event.target.value))}>
        {options.map((seconds) => <option key={seconds} value={seconds}>{formatInterval(seconds)}</option>)}
      </select>
    </label>
  );
}

/** 把接口 time 值收敛为浏览器时间输入框接受的 HH:mm。 */
function normalizeTime(value: string): string {
  return value.slice(0, 5);
}

/** 生成适合任务设置下拉框的中文时间间隔。 */
function formatInterval(seconds: number): string {
  return seconds < 60 ? `${seconds} 秒` : `${seconds / 60} 分钟`;
}

/** 以上海时区显示最近任务完成时间。 */
function formatFinishedAt(value: string | null): string {
  if (value === null) return ' · 尚未完成';
  return ` · ${new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))}`;
}
