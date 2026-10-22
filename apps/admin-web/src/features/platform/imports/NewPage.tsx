import { ImportsNewPage } from '../../../shared/imports/NewPage';
import { ImportsRuntime } from './Runtime';
export default function Page() {
  return (
    <ImportsRuntime>
      <ImportsNewPage />
    </ImportsRuntime>
  );
}
