import { onContextReset } from '../../../../core/identities';
import * as api from '../../api';
import { currentCredential, sessionRevision } from '../../../../core/session';
import { errorText } from '../../../../core/request';
import type { Binding, Community, House, SpaceNode } from '../../types';
import { bindingView, loadAll } from '../../presentation';

const versions = new WeakMap<object, number>();
const unsubscribe = new WeakMap<object, () => void>();
const choices = new WeakMap<
  object,
  { version: number; owner: string; revision: number }
>();
Component({
  options: { styleIsolation: 'apply-shared' },
  properties: {
    open: { type: Boolean, value: false },
    mode: { type: String, value: 'claim' },
    selectedId: { type: String, value: '' },
    bindings: { type: Array, value: [] as Binding[] },
  },
  data: {
    community: null as Community | null,
    path: [] as SpaceNode[],
    communities: [] as Community[],
    nodes: [] as SpaceNode[],
    houses: [] as House[],
    bindingRows: [] as ReturnType<typeof bindingView>[],
    temporaryId: '',
    query: '',
    loading: false,
    error: '',
    bodyHeight: 180,
    title: '选择小区',
  },
  observers: {
    open(open: boolean) {
      if (open) this.initialize();
      else this.invalidate();
    },
  },
  lifetimes: {
    attached() {
      unsubscribe.set(
        this,
        onContextReset(() => {
          this.invalidate();
          this.setData({
            community: null,
            path: [],
            communities: [],
            nodes: [],
            houses: [],
            bindingRows: [],
            query: '',
            temporaryId: '',
            loading: false,
            error: '',
          });
          this.triggerEvent('close');
        }),
      );
    },
    detached() {
      this.invalidate();
      unsubscribe.get(this)?.();
      unsubscribe.delete(this);
    },
  },
  methods: {
    fitHeight() {
      let height = 156;
      if (this.data.mode === 'switch')
        height = Math.max(70, this.data.bindingRows.length * 66);
      else if (!this.data.loading && !this.data.error)
        height = !this.data.community
          ? 58 + Math.max(1, this.data.communities.length) * 66
          : 58 +
            Math.max(1, this.data.nodes.length + this.data.houses.length) * 54 +
            (this.data.nodes.length ? 28 : 0) +
            (this.data.houses.length ? 28 : 0);
      const windowHeight = wx.getWindowInfo().windowHeight;
      this.setData({
        bodyHeight: Math.min(
          height,
          Math.max(160, Math.min(350, windowHeight - 220)),
        ),
      });
    },
    invalidate() {
      versions.set(this, (versions.get(this) || 0) + 1);
      choices.delete(this);
    },
    initialize() {
      this.invalidate();
      this.setData({
        community: null,
        path: [],
        query: '',
        error: '',
        communities: [],
        nodes: [],
        houses: [],
        temporaryId: this.data.selectedId,
      });
      if (this.data.mode === 'switch') {
        this.setData({
          title: '切换房屋',
          loading: false,
          bindingRows: (this.data.bindings as Binding[])
            .filter((b) => b.status === 'active' && b.effective_enabled)
            .map(bindingView),
        });
        this.fitHeight();
      } else {
        void this.load();
      }
    },
    async load() {
      const version = (versions.get(this) || 0) + 1;
      versions.set(this, version);
      choices.delete(this);
      const owner = currentCredential()?.userId;
      const revision = sessionRevision();
      const valid = () =>
        this.data.open &&
        versions.get(this) === version &&
        revision === sessionRevision() &&
        !!owner &&
        currentCredential()?.userId === owner;
      const { community, path, query } = this.data;
      this.setData({
        loading: true,
        error: '',
        title: !community ? '选择小区' : '选择房屋位置',
      });
      this.fitHeight();
      try {
        if (!community) {
          const communities = await loadAll((page) =>
            api.communities(query.trim(), page),
          );
          if (valid()) {
            choices.set(this, { version, owner: owner!, revision });
            this.setData({ communities, loading: false });
            this.fitHeight();
          }
        } else {
          const parent = path[path.length - 1];
          const [nodes, houses] = await Promise.all([
            loadAll((page) => api.nodes(community.id, parent?.id, page)),
            parent
              ? loadAll((page) =>
                  api.houses(community.id, parent.id, query.trim(), page),
                )
              : Promise.resolve([] as House[]),
          ]);
          if (valid()) {
            choices.set(this, { version, owner: owner!, revision });
            this.setData({
              nodes: query.trim()
                ? nodes.filter((node) => node.name.includes(query.trim()))
                : nodes,
              houses,
              loading: false,
            });
            this.fitHeight();
          }
        }
      } catch (error) {
        if (valid()) {
          this.setData({ loading: false, error: errorText(error) });
          this.fitHeight();
        }
      }
    },
    onSearch(event: WechatMiniprogram.CustomEvent<{ value: string }>) {
      this.setData({ query: event.detail.value });
    },
    search() {
      void this.load();
    },
    chooseCommunity(event: WechatMiniprogram.TouchEvent) {
      const community = this.data.communities.find(
        (item) => item.id === event.currentTarget.dataset.id,
      );
      if (!community) return;
      this.setData({
        community,
        path: [],
        query: '',
        nodes: [],
        houses: [],
      });
      void this.load();
    },
    chooseNode(event: WechatMiniprogram.TouchEvent) {
      const node = this.data.nodes.find(
        (item) => item.id === event.currentTarget.dataset.id,
      );
      if (!node) return;
      this.setData({
        path: [...this.data.path, node],
        query: '',
        nodes: [],
        houses: [],
      });
      void this.load();
    },
    chooseHouse(event: WechatMiniprogram.TouchEvent) {
      const context = choices.get(this);
      const community = this.data.community;
      const parent = this.data.path[this.data.path.length - 1];
      if (
        this.data.mode !== 'claim' ||
        !this.data.open ||
        this.data.loading ||
        this.data.error ||
        !community ||
        !parent ||
        !context ||
        context.version !== versions.get(this) ||
        context.revision !== sessionRevision() ||
        context.owner !== currentCredential()?.userId
      )
        return;
      const house = this.data.houses.find(
        (item) => item.id === event.currentTarget.dataset.id,
      );
      if (
        !house ||
        house.community_id !== community.id ||
        house.space_node_id !== parent.id
      )
        return;
      this.invalidate();
      this.triggerEvent('confirm', {
        house,
        community,
        path: [...this.data.path],
      });
    },
    chooseBinding(event: WechatMiniprogram.TouchEvent) {
      this.setData({ temporaryId: event.currentTarget.dataset.id });
    },
    crumb(event: WechatMiniprogram.TouchEvent) {
      const index = Number(event.currentTarget.dataset.index);
      this.setData({
        community: index < 0 ? null : this.data.community,
        path: index < 1 ? [] : this.data.path.slice(0, index),
        query: '',
        nodes: [],
        houses: [],
      });
      void this.load();
    },
    back() {
      if (this.data.loading) this.invalidate();
      if (this.data.path.length)
        this.setData({
          path: this.data.path.slice(0, -1),
          query: '',
          nodes: [],
          houses: [],
        });
      else this.setData({ community: null, query: '', communities: [] });
      void this.load();
    },
    close() {
      this.invalidate();
      this.triggerEvent('close');
    },
    confirm() {
      if (this.data.mode === 'switch') {
        const binding = (this.data.bindings as Binding[]).find(
          (b) =>
            b.id === this.data.temporaryId &&
            b.status === 'active' &&
            b.effective_enabled,
        );
        if (binding) this.triggerEvent('confirm', { binding });
      }
    },
    contact() {
      wx.showToast({
        title: '请联系所在小区物业核对房屋资料',
        icon: 'none',
        duration: 2500,
      });
    },
    prevent() {
      /* Keep drawer interactions inside the bottom layer. */
    },
  },
});
