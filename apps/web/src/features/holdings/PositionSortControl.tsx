import {
  positionSortOptions,
  type PositionSort,
  type PositionSortKey,
} from './positionSorting';

interface PositionSortControlProps {
  value: PositionSort;
  onChange: (value: PositionSort) => void;
}

/** 提供排序字段选择和独立升降序切换，适配桌面与移动端。 */
export function PositionSortControl({ value, onChange }: PositionSortControlProps) {
  const nextDirection = value.direction === 'desc' ? 'asc' : 'desc';
  const nextDirectionLabel = nextDirection === 'asc' ? '升序' : '降序';

  return (
    <div className="position-sort-control" aria-label="持仓排序">
      <select
        value={value.key}
        aria-label="排序字段"
        onChange={(event) => onChange({
          key: event.target.value as PositionSortKey,
          direction: value.direction,
        })}
      >
        {positionSortOptions.map((option) => (
          <option key={option.key} value={option.key}>{option.label}</option>
        ))}
      </select>
      <button
        type="button"
        aria-label={`切换为${nextDirectionLabel}`}
        title={`切换为${nextDirectionLabel}`}
        onClick={() => onChange({ ...value, direction: nextDirection })}
      >
        <span aria-hidden="true">{value.direction === 'desc' ? '↓' : '↑'}</span>
      </button>
    </div>
  );
}
