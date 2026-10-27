import type { components } from '../../../../../openapi/types';

export type { Page } from '../types';
export type Filters = Record<string, string | number | boolean | undefined>;

type Schemas = components['schemas'];
export type Scalar = Schemas['ImportScalar'];
export type BatchStatus = Schemas['ImportBatchStatus'];
export type NextAction = Schemas['ImportNextAction'];
export type ImportType = Schemas['ImportType'];
export type Template = Schemas['ImportTemplate'];
export type Task = Schemas['ImportTaskProgress'];
export type BatchAction = Schemas['ImportBatchAction'];
export type BatchCreate = Schemas['ImportBatchCreate'];
export type ConfirmInput = Schemas['ImportConfirm'];
export type Batch = Schemas['ImportBatch'];
export type ImportRow = Schemas['ImportRow'];
export type Issue = Schemas['ImportIssue'];
export type ImportEvent = Schemas['ImportEvent'];
export type ErrorFile = Schemas['ImportErrorFile'];
