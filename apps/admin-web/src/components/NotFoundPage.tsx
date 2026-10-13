import { Result } from 'antd';
import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <Result
      status="404"
      title="页面不存在"
      extra={<Link to="/">返回入口</Link>}
    />
  );
}
