import {
  currentCredential,
  onSessionReset,
  sessionRevision,
} from '../../core/session';

/** A page response belongs to its visible lifetime, latest load, and resident. */
export class PageScope {
  private version = 0;
  private active = false;
  private owner: string | null = null;
  private revision = -1;
  private unsubscribe: (() => void) | null = null;
  watch(reset: (visible: boolean) => void): void {
    this.unsubscribe?.();
    this.unsubscribe = onSessionReset(() => {
      const visible = this.active;
      this.leave();
      reset(visible);
    });
  }
  dispose(): void {
    this.leave();
    this.unsubscribe?.();
    this.unsubscribe = null;
  }
  enter(): boolean {
    const owner = currentCredential()?.userId || null;
    const sameOwner =
      owner !== null &&
      this.owner === owner &&
      this.revision === sessionRevision();
    this.owner = owner;
    this.revision = sessionRevision();
    this.active = true;
    this.version += 1;
    return sameOwner;
  }
  next(): () => boolean {
    const version = ++this.version;
    const owner = this.owner;
    const revision = this.revision;
    return () =>
      this.active &&
      version === this.version &&
      revision === sessionRevision() &&
      owner !== null &&
      currentCredential()?.userId === owner;
  }
  leave(): void {
    this.active = false;
    this.version += 1;
  }
  isCurrent(): boolean {
    return (
      this.active &&
      this.revision === sessionRevision() &&
      this.owner !== null &&
      currentCredential()?.userId === this.owner
    );
  }
}
