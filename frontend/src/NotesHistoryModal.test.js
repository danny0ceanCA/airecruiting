import { render, screen } from '@testing-library/react';
import NotesHistoryModal from './NotesHistoryModal';
import axios from 'axios';

jest.mock('axios', () => {
  const mockAxios = {
    get: jest.fn(),
    post: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
    create: jest.fn(),
    interceptors: {
      request: { use: jest.fn() },
      response: { use: jest.fn() }
    }
  };
  mockAxios.create.mockReturnValue(mockAxios);
  return mockAxios;
});

test('recruiter can add note but not edit', () => {
  render(
    <NotesHistoryModal
      notes={[]}
      onClose={() => {}}
      jobCode="J1"
      studentEmail="s@example.com"
      canAdd={true}
      isAdmin={false}
    />
  );
  expect(screen.getByText('Add Note')).toBeInTheDocument();
  expect(screen.queryByText('Edit')).not.toBeInTheDocument();
});

test('no add button when not allowed', () => {
  render(
    <NotesHistoryModal
      notes={[]}
      onClose={() => {}}
      jobCode="J1"
      studentEmail="s@example.com"
      canAdd={false}
      isAdmin={false}
    />
  );
  expect(screen.queryByText('Add Note')).not.toBeInTheDocument();
});

test('shows note timestamp in local time', () => {
  render(
    <NotesHistoryModal
      notes={[{ text: 'hi', timestamp: '2024-01-01T00:00:00Z' }]}
      onClose={() => {}}
      jobCode="J1"
      studentEmail="s@example.com"
      canAdd={false}
      isAdmin={false}
    />
  );
  expect(screen.getByText(/2024/)).toBeInTheDocument();
});
