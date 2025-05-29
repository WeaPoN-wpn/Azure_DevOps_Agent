// get_workitem_id.js
// Node.js script to fetch a work item and all its related work items recursively by id, saving to storage/workitem_<id>.json
import fs from 'fs';
import path from 'path';
import axios from 'axios';
import dotenv from 'dotenv';
import readline from 'readline';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Ensure storage and storage/workitem_images directories exist
const STORAGE_DIR = path.join(__dirname, 'storage');
const IMAGES_DIR = path.join(STORAGE_DIR, 'workitem_images');
if (!fs.existsSync(STORAGE_DIR)) {
  fs.mkdirSync(STORAGE_DIR);
}
if (!fs.existsSync(IMAGES_DIR)) {
  fs.mkdirSync(IMAGES_DIR);
}

dotenv.config({ path: path.join(__dirname, '.env') });

const ORGANIZATION = process.env.ADO_ORG;
const PROJECT = process.env.ADO_PROJECT;
const PAT = process.env.ADO_PAT;

const ORG_ENC = encodeURIComponent(ORGANIZATION);
const PROJ_ENC = encodeURIComponent(PROJECT);
const WORKITEM_DETAIL_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/_apis/wit/workitems/`;
const WORKITEM_COMMENTS_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/_apis/wit/workItems/`;

const authHeader = {
  Authorization: 'Basic ' + Buffer.from(':' + PAT).toString('base64'),
  'Content-Type': 'application/json',
  Accept: 'application/json',
};

// Recursive fetch for work item details (with deduplication)
const fetchedWorkItems = new Map();

async function fetchWorkItemDetails(ids) {
  let queue = Array.from(new Set(ids));
  let result = [];
  while (queue.length > 0) {
    const id = queue.shift();
    if (fetchedWorkItems.has(id)) continue;
    console.log(`Fetching details for work item ${id}...`);
    let fields = {};
    let description = '';
    let assigned_to = null;
    let title = '';
    let state = '';
    let comments = [];
    let parent_work_items = [];
    let child_work_items = [];
    let related_work_items = [];
    let image_files = [];
    // Fetch main fields
    try {
      const detailUrl = `${WORKITEM_DETAIL_URL}${id}?$expand=relations&api-version=7.0`;
      const detailResp = await axios.get(detailUrl, { headers: authHeader });
      fields = detailResp.data.fields || {};
      description = fields['System.Description'] || '';
      assigned_to = fields['System.AssignedTo']?.displayName || fields['System.AssignedTo'] || null;
      title = fields['System.Title'] || '';
      state = fields['System.State'] || '';
      // Relations
      const relations = detailResp.data.relations || [];
      for (const rel of relations) {
        if (rel.rel === 'System.LinkTypes.Hierarchy-Reverse') {
          const match = rel.url.match(/workItems\/(\d+)/);
          if (match) parent_work_items.push(Number(match[1]));
        } else if (rel.rel === 'System.LinkTypes.Hierarchy-Forward') {
          const match = rel.url.match(/workItems\/(\d+)/);
          if (match) child_work_items.push(Number(match[1]));
        } else if (rel.rel === 'System.LinkTypes.Related') {
          const match = rel.url.match(/workItems\/(\d+)/);
          if (match) related_work_items.push(Number(match[1]));
        } else if (rel.rel === 'AttachedFile' && rel.url.includes('_apis/wit/attachments/')) {
          const fileName = rel.attributes?.name || '';
          if (fileName.match(/\.(png|jpg|jpeg|gif)$/i)) {
            // Download the image
            const imgUrl = rel.url + '?api-version=7.0';
            const ext = path.extname(fileName) || '.png';
            const imgFileName = `workitem_${id}_${image_files.length + 1}${ext}`;
            const imgPath = path.join(IMAGES_DIR, imgFileName);
            try {
              const imgResp = await axios.get(imgUrl, { headers: authHeader, responseType: 'arraybuffer' });
              fs.writeFileSync(imgPath, imgResp.data);
              image_files.push(imgFileName);
              console.log(`Downloaded image: ${imgFileName}`);
            } catch (imgErr) {
              console.log(`Failed to download image for work item ${id}: ${imgFileName}`);
            }
          }
        }
      }
      // Add related work items to queue for recursion
      for (const relId of [...parent_work_items, ...child_work_items, ...related_work_items]) {
        if (!fetchedWorkItems.has(relId) && !queue.includes(relId)) {
          queue.push(relId);
        }
      }
    } catch (e) {
      console.log(`Failed to fetch main details for work item ${id}:`, e.response?.data?.message || e.message);
    }
    // Fetch comments
    try {
      const commentsUrl = `${WORKITEM_COMMENTS_URL}${id}/comments?api-version=7.0-preview`;
      const commentsResp = await axios.get(commentsUrl, { headers: authHeader });
      comments = (commentsResp.data.comments || []).map(c => ({
        id: c.id,
        text: c.text,
        createdBy: c.createdBy?.displayName,
        createdDate: c.createdDate,
      }));
    } catch (e) {
      console.log(`Failed to fetch comments for work item ${id}:`, e.response?.data?.message || e.message);
    }
    // Helper: extract image URLs from HTML
    function extractImageUrls(html) {
      if (!html) return [];
      const regex = /<img [^>]*src=["']([^"'>]+)["'][^>]*>/gi;
      let urls = [];
      let match;
      while ((match = regex.exec(html))) {
        urls.push(match[1]);
      }
      return urls;
    }
    // Download images from description
    let descImages = extractImageUrls(description);
    for (let j = 0; j < descImages.length; j++) {
      const imgUrl = descImages[j];
      const imgFileName = `workitem_${id}_${image_files.length + 1}.png`;
      const imgPath = path.join(IMAGES_DIR, imgFileName);
      try {
        const imgResp = await axios.get(imgUrl, { headers: authHeader, responseType: 'arraybuffer' });
        fs.writeFileSync(imgPath, imgResp.data);
        image_files.push(imgFileName);
        console.log(`Downloaded image from description: ${imgFileName}`);
      } catch (imgErr) {
        console.log(`Failed to download image from description for work item ${id}: ${imgFileName}`);
      }
    }
    // Download images from comments
    for (let c = 0; c < comments.length; c++) {
      let commentImages = extractImageUrls(comments[c].text);
      for (let k = 0; k < commentImages.length; k++) {
        const imgUrl = commentImages[k];
        const imgFileName = `workitem_${id}_${image_files.length + 1}.png`;
        const imgPath = path.join(IMAGES_DIR, imgFileName);
        try {
          const imgResp = await axios.get(imgUrl, { headers: authHeader, responseType: 'arraybuffer' });
          fs.writeFileSync(imgPath, imgResp.data);
          image_files.push(imgFileName);
          console.log(`Downloaded image from comment: ${imgFileName}`);
        } catch (imgErr) {
          console.log(`Failed to download image from comment for work item ${id}: ${imgFileName}`);
        }
      }
    }
    // Comments: flatten to text array for compatibility
    const comments_text = comments.map(c => c.text);
    const workItemObj = {
      id,
      title,
      state,
      assigned_to,
      description,
      comments: comments_text,
      parent_work_items,
      child_work_items,
      related_work_items,
      image_files,
    };
    fetchedWorkItems.set(id, workItemObj);
    result.push(workItemObj);
  }
  return result;
}

async function askWorkItemId() {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(resolve => {
    rl.question('Please enter the work item id: ', answer => {
      rl.close();
      resolve(answer.trim());
    });
  });
}

async function main() {
  try {
    const idStr = await askWorkItemId();
    const id = parseInt(idStr, 10);
    if (!id || isNaN(id)) {
      console.log('Invalid work item id.');
      return;
    }
    const allDetails = await fetchWorkItemDetails([id]);
    const uniqueDetails = Array.from(fetchedWorkItems.values());
    const outputFile = path.join(STORAGE_DIR, `workitem_${id}.json`);
    fs.writeFileSync(outputFile, JSON.stringify(uniqueDetails, null, 2), 'utf-8');
    console.log(`Success! ${uniqueDetails.length} work items with details saved to ${outputFile}`);
  } catch (e) {
    console.error('Error:', e.response?.data || e.message);
  }
}

main();
