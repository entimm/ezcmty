// Match Umi's router version while testing without its generated runtime.
export {
  Link,
  Outlet,
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
  useParams,
} from 'react-router-dom';
export const history = {
  block: (callback: unknown) => {
    void callback;
    return () => {};
  },
};
