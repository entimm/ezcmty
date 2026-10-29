import type { ComponentProps } from 'react';
import { useAdmin } from '../../shared/context';
import { PropertyEditor as SharedEditor } from '../../shared/property-business/Editor';

export function PropertyEditor(
  props: Omit<ComponentProps<typeof SharedEditor>, 'setDirty'>,
) {
  const { setDirty } = useAdmin();
  return <SharedEditor {...props} setDirty={setDirty} />;
}
