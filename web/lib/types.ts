/** Shapes returned by the database views the site is allowed to read. */

export interface HallLatest {
  hall_id: string;
  name: string;
  ts: string;
  count: number;
  model_version: string;
  roi_version: string;
  camera_epoch: number;
  opens_at: string | null;
  closes_at: string | null;
}

export interface CountPoint {
  ts: string;
  count: number;
}

export interface HallSummary {
  hall_id: string;
  name: string;
  opens_at: string | null;
  closes_at: string | null;
}
