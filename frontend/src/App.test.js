import { render, screen } from '@testing-library/react';
import App from './App';
import Metrics from './Metrics';
import { BrowserRouter } from 'react-router-dom';
import api from './api';
import axios from 'axios';

jest.mock('axios', () => {
  const mockAxios = { get: jest.fn(), post: jest.fn(), create: jest.fn() };
  mockAxios.create.mockReturnValue(mockAxios);
  return mockAxios;
});

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

test('renders login form', () => {
  render(<App />);
  const heading = screen.getByRole('heading', { name: /login/i });
  expect(heading).toBeInTheDocument();
});

test('admin metrics shows placement rate', async () => {
  api.get.mockResolvedValueOnce({
    data: {
      total_student_profiles: 1,
      total_jobs_posted: 1,
      total_matches: 1,
      average_match_score: 0.8,
      placement_rate: 0.72,
      avg_time_to_placement_days: 14.2,
      license_breakdown: {},
      rematch_rate: 0.06,
    },
  });

  const payload = { role: 'admin', exp: Math.floor(Date.now() / 1000) + 1000 };
  const token = `header.${btoa(JSON.stringify(payload))}.sig`;
  localStorage.setItem('token', token);
  render(
    <BrowserRouter>
      <Metrics />
    </BrowserRouter>
  );
  expect(await screen.findByText(/Placement Rate/i)).toBeInTheDocument();
  localStorage.clear();
});
