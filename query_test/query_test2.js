// query_test2.js
// Node.js script to fetch work items containing "CN Calculation" or "Currency Neutral" in the title
// Limited to one level of recursion for related work items
import fs from 'fs';
import path from 'path';
import axios from 'axios';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Ensure storage directory exists
const STORAGE_DIR = path.join(__dirname, 'storage');
// const IMAGES_DIR = path.join(STORAGE_DIR, 'workitem_images'); // Commented out - no image collection
if (!fs.existsSync(STORAGE_DIR)) {
  fs.mkdirSync(STORAGE_DIR, { recursive: true });
}
// if (!fs.existsSync(IMAGES_DIR)) {  // Commented out - no image collection
//   fs.mkdirSync(IMAGES_DIR, { recursive: true });
// }

const OUTPUT_FILE = path.join(STORAGE_DIR, 'workitem_details.json');

dotenv.config({ path: path.join(__dirname, '.env') });

const ORGANIZATION = process.env.ADO_ORG;
const PROJECT = process.env.ADO_PROJECT;
const PAT = process.env.ADO_PAT;
const TEAM = process.env.ADO_TEAM || `${PROJECT} Team`;

// Validate required environment variables
if (!ORGANIZATION || !PROJECT || !PAT) {
  console.error('Missing required environment variables: ADO_ORG, ADO_PROJECT, ADO_PAT');
  process.exit(1);
}

const ORG_ENC = encodeURIComponent(ORGANIZATION);
const PROJ_ENC = encodeURIComponent(PROJECT);

// Azure DevOps API URLs
const WIQL_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/_apis/wit/wiql?api-version=7.0`;
const WORKITEM_DETAIL_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/_apis/wit/workitems/`;
const WORKITEM_COMMENTS_URL = `https://dev.azure.com/${ORG_ENC}/${PROJ_ENC}/_apis/wit/workItems/`;

const authHeader = {
  Authorization: 'Basic ' + Buffer.from(':' + PAT).toString('base64'),
  'Content-Type': 'application/json',
  Accept: 'application/json',
};

// Track fetched work items to avoid duplicates
const fetchedWorkItems = new Map();

// Fetch work item details with one level of recursion only
async function fetchWorkItemDetails(ids) {
  const initialIds = Array.from(new Set(ids));
  const relatedIds = new Set();
  
  console.log(`Starting to fetch ${initialIds.length} CN Calculation/Currency Neutral work items...`);
  
  // First pass: fetch initial work items and collect their direct relationships
  for (const id of initialIds) {
    if (fetchedWorkItems.has(id)) continue;
    
    console.log(`Fetching details for CN/Currency Neutral work item ${id}...`);
    
    const workItem = await fetchSingleWorkItem(id, true); // true = collect related IDs
    if (workItem) {
      fetchedWorkItems.set(id, workItem);
      
      // Collect related work item IDs for second pass
      workItem.parent_work_items.forEach(rid => relatedIds.add(rid));
      workItem.child_work_items.forEach(rid => relatedIds.add(rid));
      workItem.related_work_items.forEach(rid => relatedIds.add(rid));
    }
    
    // Add small delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  
  // Second pass: fetch only the directly related work items (one level recursion)
  const relatedIdsArray = Array.from(relatedIds).filter(id => !fetchedWorkItems.has(id));
  console.log(`Fetching ${relatedIdsArray.length} related work items (one level)...`);
  
  for (const id of relatedIdsArray) {
    if (fetchedWorkItems.has(id)) continue;
    
    console.log(`Fetching related work item ${id}...`);
    
    const workItem = await fetchSingleWorkItem(id, false); // false = don't collect more related IDs
    if (workItem) {
      fetchedWorkItems.set(id, workItem);
    }
    
    // Add small delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  
  return Array.from(fetchedWorkItems.values());
}

// Fetch a single work item's details
async function fetchSingleWorkItem(id, collectRelatedIds = false) {
  let workItem = {
    id,
    title: '',
    state: '',
    assigned_to: null,
    description: '',
    comments: [],
    parent_work_items: [],
    child_work_items: [],
    related_work_items: [],
    image_files: [] // Keep empty - no image collection
  };
  
  try {
    // Fetch main work item details with relations
    const detailUrl = `${WORKITEM_DETAIL_URL}${id}?$expand=relations&api-version=7.0`;
    const detailResp = await axios.get(detailUrl, { headers: authHeader });
    const fields = detailResp.data.fields || {};
    
    // Extract basic fields
    workItem.title = fields['System.Title'] || '';
    workItem.state = fields['System.State'] || '';
    workItem.description = fields['System.Description'] || '';
    workItem.assigned_to = fields['System.AssignedTo']?.displayName || 
                         fields['System.AssignedTo'] || null;
    
    // Process relations only if we need to collect related IDs
    if (collectRelatedIds) {
      const relations = detailResp.data.relations || [];
      for (const rel of relations) {
        const match = rel.url.match(/workItems\/(\d+)/);
        const relatedId = match ? Number(match[1]) : null;
        
        if (relatedId) {
          switch (rel.rel) {
            case 'System.LinkTypes.Hierarchy-Reverse':
              workItem.parent_work_items.push(relatedId);
              break;
            case 'System.LinkTypes.Hierarchy-Forward':
              workItem.child_work_items.push(relatedId);
              break;
            case 'System.LinkTypes.Related':
              workItem.related_work_items.push(relatedId);
              break;
          }
        }
        
        // Commented out - Image file handling
        // if (rel.rel === 'AttachedFile' && rel.url.includes('_apis/wit/attachments/')) {
        //   const fileName = rel.attributes?.name || '';
        //   if (fileName.match(/\.(png|jpg|jpeg|gif|bmp|svg)$/i)) {
        //     const imgUrl = rel.url + '?api-version=7.0';
        //     const downloadedFileName = await downloadImage(
        //       imgUrl, 
        //       id, 
        //       workItem.image_files.length + 1, 
        //       'attachment'
        //     );
        //     if (downloadedFileName) {
        //       workItem.image_files.push(downloadedFileName);
        //     }
        //   }
        // }
      }
    }
    
  } catch (error) {
    console.log(`Failed to fetch main details for work item ${id}:`, 
                error.response?.data?.message || error.message);
    return null;
  }
  
  try {
    // Fetch comments
    const commentsUrl = `${WORKITEM_COMMENTS_URL}${id}/comments?api-version=7.0-preview`;
    const commentsResp = await axios.get(commentsUrl, { headers: authHeader });
    const comments = commentsResp.data.comments || [];
    
    // Process comments - extract text only (no image processing)
    workItem.comments = comments.map(comment => comment.text || '');
    
    // Commented out - Image extraction from comments
    // for (const comment of comments) {
    //   const commentImages = extractImageUrls(comment.text);
    //   for (const imgUrl of commentImages) {
    //     const downloadedFileName = await downloadImage(
    //       imgUrl,
    //       id,
    //       workItem.image_files.length + 1,
    //       'comment'
    //     );
    //     if (downloadedFileName) {
    //       workItem.image_files.push(downloadedFileName);
    //     }
    //   }
    // }
    
  } catch (error) {
    console.log(`Failed to fetch comments for work item ${id}:`, 
                error.response?.data?.message || error.message);
  }
  
  // Commented out - Image extraction from description
  // const descriptionImages = extractImageUrls(workItem.description);
  // for (const imgUrl of descriptionImages) {
  //   const downloadedFileName = await downloadImage(
  //     imgUrl,
  //     id,
  //     workItem.image_files.length + 1,
  //     'description'
  //   );
  //   if (downloadedFileName) {
  //     workItem.image_files.push(downloadedFileName);
  //   }
  // }
  
  return workItem;
}

// Commented out - Image extraction helper function
// function extractImageUrls(html) {
//   if (!html) return [];
//   
//   const regex = /<img [^>]*src=["']([^"'>]+)["'][^>]*>/gi;
//   const urls = [];
//   let match;
//   
//   while ((match = regex.exec(html))) {
//     urls.push(match[1]);
//   }
//   
//   return urls;
// }

// Commented out - Image download function
// async function downloadImage(imageUrl, workItemId, imageIndex, description = '') {
//   try {
//     const ext = path.extname(imageUrl) || '.png';
//     const imgFileName = `cn_workitem_${workItemId}_${imageIndex}${ext}`;
//     const imgPath = path.join(IMAGES_DIR, imgFileName);
//     
//     const imgResp = await axios.get(imageUrl, { 
//       headers: authHeader, 
//       responseType: 'arraybuffer',
//       timeout: 30000 // 30 second timeout
//     });
//     
//     fs.writeFileSync(imgPath, imgResp.data);
//     console.log(`Downloaded image ${description}: ${imgFileName}`);
//     return imgFileName;
//   } catch (error) {
//     console.log(`Failed to download image for work item ${workItemId}: ${error.message}`);
//     return null;
//   }
// }

// Main function to fetch CN Calculation / Currency Neutral work items
async function main() {
  try {
    console.log('Starting CN Calculation/Currency Neutral work items collection (one level recursion)...');
    console.log(`Organization: ${ORGANIZATION}`);
    console.log(`Project: ${PROJECT}`);
    
    // WIQL query to find work items with "CN Calculation" or "Currency Neutral" in title (case insensitive)
    const wiql = {
      query: `SELECT [System.Id], [System.Title], [System.State], [System.AssignedTo] 
              FROM WorkItems 
              WHERE [System.Title] CONTAINS 'CN Calculation' 
                 OR [System.Title] CONTAINS 'Currency Neutral'
                 OR [System.Title] CONTAINS 'cn calculation'
                 OR [System.Title] CONTAINS 'currency neutral'
                 OR [System.Title] CONTAINS 'CN CALCULATION'
                 OR [System.Title] CONTAINS 'CURRENCY NEUTRAL'
              ORDER BY [System.Id] ASC`
    };
    
    console.log('Querying work items with "CN Calculation" or "Currency Neutral" in title...');
    const wiqlResp = await axios.post(WIQL_URL, wiql, { headers: authHeader });
    const workItems = wiqlResp.data.workItems || [];
    const ids = workItems.map(wi => wi.id);
    
    console.log(`Found ${ids.length} work items containing "CN Calculation" or "Currency Neutral" in title.`);
    
    if (ids.length === 0) {
      const emptyResult = [];
      fs.writeFileSync(OUTPUT_FILE, JSON.stringify(emptyResult, null, 2), 'utf-8');
      console.log('No CN Calculation/Currency Neutral work items found. Empty file created.');
      return;
    }
    
    // Log found work item IDs
    console.log('CN Calculation/Currency Neutral Work Item IDs:', ids.join(', '));
    
    // Fetch work item details with one level of recursion
    console.log('Fetching detailed information (one level recursion)...');
    const allWorkItems = await fetchWorkItemDetails(ids);
    
    // Sort by ID for consistent output
    allWorkItems.sort((a, b) => a.id - b.id);
    
    // Write to file
    fs.writeFileSync(OUTPUT_FILE, JSON.stringify(allWorkItems, null, 2), 'utf-8');
    
    console.log(`Success! ${allWorkItems.length} work items saved to ${OUTPUT_FILE}`);
    
    // Summary
    const targetItems = allWorkItems.filter(item => {
      const title = item.title.toUpperCase();
      return title.includes('CN CALCULATION') || title.includes('CURRENCY NEUTRAL');
    });
    
    console.log('\n=== SUMMARY ===');
    console.log(`Primary CN Calculation/Currency Neutral work items: ${targetItems.length}`);
    console.log(`Total work items (including related): ${allWorkItems.length}`);
    console.log(`Image collection: DISABLED (commented out)`);
    
    // List CN Calculation/Currency Neutral work items
    console.log('\n=== CN CALCULATION / CURRENCY NEUTRAL WORK ITEMS ===');
    targetItems.forEach(item => {
      console.log(`ID: ${item.id} | State: ${item.state} | Title: ${item.title}`);
      if (item.parent_work_items.length > 0) {
        console.log(`  └─ Parent items: ${item.parent_work_items.join(', ')}`);
      }
      if (item.child_work_items.length > 0) {
        console.log(`  └─ Child items: ${item.child_work_items.join(', ')}`);
      }
      if (item.related_work_items.length > 0) {
        console.log(`  └─ Related items: ${item.related_work_items.join(', ')}`);
      }
    });
    
  } catch (error) {
    console.error('Error:', error.response?.data || error.message);
    process.exit(1);
  }
}

// Run the script
main();
