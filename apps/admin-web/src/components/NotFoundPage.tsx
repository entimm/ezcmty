import { Result } from 'antd';
import { Link } from '@umijs/max';

export default function NotFoundPage() {
  return (
    <Result
      status="404"
      title="页面不存在"
      extra={<Link to="/">返回入口</Link>}
    />
  );
}
