import { Box, IconButton, Tooltip } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';

interface SidebarProps {
  onCreateNote: () => void;
}

const Sidebar = ({ onCreateNote }: SidebarProps) => {
  return (
    <Box
      sx={{
        width: 60,
        bgcolor: 'grey.100',
        borderRight: 1,
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        py: 2,
      }}
    >
      <Tooltip title="새 메모" placement="right">
        <IconButton
          onClick={onCreateNote}
          sx={{
            color: 'primary.main',
            '&:hover': {
              bgcolor: 'grey.200',
            },
          }}
        >
          <AddIcon />
        </IconButton>
      </Tooltip>
    </Box>
  );
};

export default Sidebar; 