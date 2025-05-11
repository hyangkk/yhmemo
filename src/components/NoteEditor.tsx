import { Box, TextField } from '@mui/material';
import type { Note } from '../types';
import { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';

interface NoteEditorProps {
  note: Note | null;
  onUpdateNote: (note: Note) => void;
}

const NoteEditor = ({ note, onUpdateNote }: NoteEditorProps) => {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');

  useEffect(() => {
    if (note) {
      setTitle(note.title);
      setContent(note.content);
    } else {
      setTitle('');
      setContent('');
    }
  }, [note]);

  const handleTitleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setTitle(e.target.value);
  };

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setContent(e.target.value);
  };

  const handleTitleBlur = () => {
    if (note) {
      onUpdateNote({ ...note, title });
    }
  };

  const handleContentBlur = () => {
    if (note) {
      onUpdateNote({ ...note, content });
    }
  };

  if (!note) {
    return (
      <Box
        sx={{
          flex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.paper',
        }}
      >
        메모를 선택하거나 새 메모를 만들어주세요
      </Box>
    );
  }

  return (
    <Box
      sx={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'background.paper',
        p: 2,
      }}
    >
      <TextField
        fullWidth
        variant="standard"
        value={title}
        onChange={handleTitleChange}
        onBlur={handleTitleBlur}
        placeholder="제목"
        sx={{ mb: 2 }}
      />
      <TextField
        fullWidth
        multiline
        value={content}
        onChange={handleContentChange}
        onBlur={handleContentBlur}
        placeholder="내용을 입력하세요"
        sx={{ flex: 1 }}
        InputProps={{
          sx: {
            height: '100%',
            '& textarea': {
              height: '100% !important',
            },
          },
        }}
      />
      <Box sx={{ mt: 2, p: 2, bgcolor: '#f6f8fa', borderRadius: 2, minHeight: 100 }}>
        <ReactMarkdown>{content}</ReactMarkdown>
      </Box>
    </Box>
  );
};

export default NoteEditor; 