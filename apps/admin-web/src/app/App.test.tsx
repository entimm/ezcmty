import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import App from './App';

describe('admin shell', () => {
  it('renders both portal entry points', () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText('进入平台管理端')).toBeInTheDocument();
    expect(screen.getByText('进入物业管理端')).toBeInTheDocument();
  });
});
