import { Alert, Button, Form, Input, InputNumber, Select, Space } from 'antd';
import { usePropertySession } from '../hooks';
import { useHousingApi } from './hooks';
import type {
  House,
  HouseInput,
  HouseOwner,
  OwnerInput,
  SpaceInput,
  SpaceNode,
  SpaceType,
} from './api';
import { HousingFormDrawer } from './HousingFormDrawer';
import { LocationPicker } from './SpaceTree';

function ExternalCode() {
  return (
    <Form.Item name="external_code" label="外部编号" rules={[{ max: 64 }]}>
      <Input allowClear />
    </Form.Item>
  );
}
function OwnerFields({ index }: { index?: number }) {
  return (
    <>
      <Form.Item
        name={index === undefined ? 'name' : [index, 'name']}
        label="业主姓名"
        rules={[{ required: true, whitespace: true }, { max: 80 }]}
      >
        <Input autoComplete="off" />
      </Form.Item>
      <Form.Item
        name={index === undefined ? 'phone' : [index, 'phone']}
        label="手机号"
        rules={[
          { required: true },
          {
            pattern: /^(?:(?:\+86|0086))?1[3-9][0-9]{9}$/,
            message: '请输入大陆手机号，可带 +86 或 0086 前缀',
          },
        ]}
      >
        <Input type="tel" autoComplete="off" />
      </Form.Item>
    </>
  );
}
export function SpaceEditor({
  communityId,
  node,
  parent,
  done,
}: {
  communityId: string;
  node?: SpaceNode;
  parent?: SpaceNode;
  done: () => void;
}) {
  const api = useHousingApi();
  const types: SpaceType[] =
    parent?.node_type === 'phase'
      ? ['building']
      : parent?.node_type === 'building'
        ? ['unit']
        : ['phase', 'building'];
  const names = { phase: '分区', building: '楼栋', unit: '单元' };
  return (
    <HousingFormDrawer<SpaceInput>
      title={node ? '编辑空间' : '新增空间'}
      fields={['node_type', 'name', 'external_code', 'sort_order']}
      initialValues={node ?? { node_type: types[0], sort_order: 0 }}
      done={done}
      save={(values) => {
        const editable = {
          name: values.name,
          external_code: values.external_code?.trim() || null,
          sort_order: values.sort_order ?? 0,
        };
        return node
          ? api.updateNode(communityId, node.id, editable)
          : api.createNode(communityId, {
              ...editable,
              parent_id: parent?.id ?? null,
              node_type: values.node_type,
            });
      }}
    >
      <p>
        所属位置：
        {node
          ? [...node.ancestors.map((part) => part.name)].join('／') || '小区'
          : (parent?.name ?? '小区')}
      </p>
      <Form.Item name="node_type" label="空间类型" rules={[{ required: true }]}>
        <Select
          disabled={!!node}
          options={(node ? [node.node_type] : types).map((type) => ({
            value: type,
            label: names[type],
          }))}
        />
      </Form.Item>
      <Form.Item
        name="name"
        label="空间名称"
        rules={[{ required: true, whitespace: true }, { max: 80 }]}
      >
        <Input />
      </Form.Item>
      <ExternalCode />
      <Form.Item name="sort_order" label="排序" rules={[{ required: true }]}>
        <InputNumber min={0} max={2147483647} precision={0} />
      </Form.Item>
    </HousingFormDrawer>
  );
}
export function HouseEditor({
  communityId,
  house,
  selected,
  done,
}: {
  communityId: string;
  house?: House;
  selected?: SpaceNode;
  done: () => void;
}) {
  const api = useHousingApi();
  const { hasPermission } = usePropertySession();
  return (
    <HousingFormDrawer<HouseInput>
      title={house ? '编辑房屋' : '新增房屋'}
      fields={[
        'space_node_id',
        'room_no',
        'floor_no',
        'external_code',
        'owners',
      ]}
      initialValues={
        house ?? {
          space_node_id:
            selected && selected.node_type !== 'phase'
              ? selected.id
              : undefined,
          owners: [],
        }
      }
      done={done}
      save={(values) => {
        const editable = {
          room_no: values.room_no,
          floor_no: values.floor_no ?? null,
          external_code: values.external_code?.trim() || null,
        };
        return house
          ? api.updateHouse(communityId, house.id, editable)
          : api.createHouse(communityId, {
              ...editable,
              space_node_id: values.space_node_id,
              ...(hasPermission('property.house_owner.create')
                ? { owners: values.owners ?? [] }
                : {}),
            });
      }}
    >
      {house ? (
        <p>所属位置：{house.display_address}（归属固定）</p>
      ) : (
        <Form.Item
          name="space_node_id"
          label="所属楼栋或单元"
          rules={[{ required: true, message: '请选择楼栋或单元' }]}
        >
          <LocationPicker communityId={communityId} />
        </Form.Item>
      )}
      <Form.Item
        name="room_no"
        label="房号"
        rules={[{ required: true, whitespace: true }, { max: 32 }]}
      >
        <Input />
      </Form.Item>
      <Form.Item name="floor_no" label="楼层">
        <InputNumber min={-32768} max={32767} precision={0} />
      </Form.Item>
      <ExternalCode />
      {!house && hasPermission('property.house_owner.create') && (
        <>
          <Alert
            type="info"
            title="可同时登记多名业主，也可稍后补录。"
            style={{ marginBottom: 16 }}
          />
          <Form.List name="owners">
            {(fields, { add, remove }) => (
              <>
                {fields.map((field) => (
                  <div
                    key={field.key}
                    style={{
                      border: '1px solid #ddd',
                      padding: 12,
                      marginBottom: 12,
                    }}
                  >
                    <OwnerFields index={field.name} />
                    <Button danger onClick={() => remove(field.name)}>
                      移除此业主
                    </Button>
                  </div>
                ))}
                <Space style={{ marginBottom: 16 }}>
                  <Button onClick={() => add()}>添加业主</Button>
                </Space>
              </>
            )}
          </Form.List>
        </>
      )}
    </HousingFormDrawer>
  );
}
export function OwnerEditor({
  communityId,
  houseId,
  owner,
  done,
}: {
  communityId: string;
  houseId: string;
  owner?: HouseOwner;
  done: () => void;
}) {
  const api = useHousingApi();
  return (
    <HousingFormDrawer<OwnerInput>
      title={owner ? '编辑业主资料' : '新增业主'}
      fields={['name', 'phone']}
      initialValues={owner}
      done={done}
      save={(values) =>
        owner
          ? api.updateOwner(communityId, houseId, owner.id, values)
          : api.createOwner(communityId, houseId, values)
      }
    >
      <Alert
        type="info"
        title="资料纠错可编辑；更换业主请停用原登记，再新增业主。"
        style={{ marginBottom: 16 }}
      />
      <OwnerFields />
    </HousingFormDrawer>
  );
}
